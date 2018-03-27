import sys
import os
import random
import string

import click
from pyflow import WorkflowRunner, CommandTaskRunner, TaskManager, WorkflowRunnerThreadSharedData
from pyflow import *
from subprocess import call


class FluxRunMode(object):
    data = { "local" : ModeInfo(defaultCores=1,
                                defaultMemMbPerCore=siteConfig.defaultHostMemMbPerCore,
                                defaultIsRetry=False),
             "sge"   : ModeInfo(defaultCores=getSGEJobsDefault(),
                                defaultMemMbPerCore="unlimited",
                                defaultIsRetry=True),
             "flux"   : ModeInfo(defaultCores=getSGEJobsDefault(),
                                defaultMemMbPerCore="unlimited",
                                defaultIsRetry=True) }


class FluxRetryParam(RetryParam):
    def _finalize(self):
        """
        decide whether to turn retry off based on retry and run modes:
        """
        if (self._retry_mode == "nonlocal") and \
                (not FluxRunMode.data[self._run_mode].defaultIsRetry) :
            self.max = 0
        else :
            self.max = int(self._retry_max)


class FluxWorkflowRunner(WorkflowRunner):
    def _cdata(self) :
        # We're doing this convoluted setup only to avoid having a
        # ctor for ease of use by the client. See what pyFlow goes
        # through for you client code??
        #
        try:
            return self._constantData
        except AttributeError:
            self._constantData = FluxWorkflowRunnerThreadSharedData()
            return self._constantData

    def _startTaskManager(self) :
        # Start a new task manager if one isn't already running. If it is running
        # provide a hint that a new task has just been added to the workflow.
        #
        if (self._tman is not None) and (self._tman.isAlive()) :
            self._tdag.isFinishedEvent.set()
            return
        if not self._cdata().isTaskManagerException :
            self._tman = FluxTaskManager(self._cdata(), self._tdag)
            self._tman.start()


class FluxWorkflowRunnerThreadSharedData(WorkflowRunnerThreadSharedData):
    @staticmethod
    def _validateFixParam(param):
        """
        validate and refine raw run() parameters for use by workflow
        """

        param.mailTo = setzer(param.mailTo)
        param.schedulerArgList = lister(param.schedulerArgList)
        if param.successMsg is not None :
            if not isString(param.successMsg) :
                raise Exception("successMsg argument to WorkflowRunner.run() is not a string")

        # create combined task retry settings manager:
        param.retry=FluxRetryParam(param.mode,
                               param.retryMax,
                               param.retryWait,
                               param.retryWindow,
                               param.retryMode)

        # setup resource parameters
        if param.nCores is None :
            param.nCores = FluxRunMode.data[param.mode].defaultCores

        # ignore total available memory settings in non-local modes:
        if param.mode != "local" :
            param.memMb = "unlimited"

        if param.mode in ("sge", "flux") :
            if siteConfig.maxSGEJobs != "unlimited" :
                if ((param.nCores == "unlimited") or
                    (int(param.nCores) > int(siteConfig.maxSGEJobs))) :
                    param.nCores = int(siteConfig.maxSGEJobs)

        if param.nCores != "unlimited" :
            param.nCores = int(param.nCores)
            if param.nCores < 1 :
                raise Exception("Invalid run mode nCores argument: %s. Value must be 'unlimited' or an integer no less than 1" % (param.nCores))

        if param.memMb is None :
            if param.nCores == "unlimited" :
                param.memMb = "unlimited"
            mpc = FluxRunMode.data[param.mode].defaultMemMbPerCore
            if mpc == "unlimited" :
                param.memMb = "unlimited"
            else :
                param.memMb = mpc * param.nCores
        elif param.memMb != "unlimited" :
            param.memMb = int(param.memMb)
            if param.memMb < 1 :
                raise Exception("Invalid run mode memMb argument: %s. Value must be 'unlimited' or an integer no less than 1" % (param.memMb))

        # verify/normalize input settings:
        if param.mode not in FluxRunMode.data.keys() :
            raise Exception("Invalid mode argument '%s'. Accepted modes are {%s}." \
                            % (param.mode, ",".join(FluxRunMode.data.keys())))

        if param.mode == "sge" :
            # TODO not-portable to windows (but is this a moot point -- all of sge mode is non-portable, no?):
            def checkSgeProg(prog) :
                proc = subprocess.Popen(("which", prog), stdout=open(os.devnull, "w"), shell=False)
                retval = proc.wait()
                if retval != 0 : raise Exception("Run mode is sge, but no %s in path" % (prog))
            checkSgeProg("qsub")
            checkSgeProg("qstat")

        if param.mode == "flux":
            def checkSgeProg(prog) :
                proc = subprocess.Popen(("which", prog), stdout=open(os.devnull, "w"), shell=False)
                retval = proc.wait()
                if retval != 0 : raise Exception("Run mode is sge, but no %s in path" % (prog))
            checkSgeProg("qsub")
            checkSgeProg("qstat")


        stateDir = os.path.join(param.dataDir, "state")
        if param.isContinue == "Auto" :
            param.isContinue = os.path.exists(stateDir)

        if param.isContinue :
            if not os.path.exists(stateDir) :
                raise Exception("Cannot continue run without providing a pyflow dataDir containing previous state.: '%s'" % (stateDir))

        for email in param.mailTo :
            if not verifyEmailAddy(email):
                raise Exception("Invalid email address: '%s'" % (email))




class FluxTaskManager(TaskManager):
    """
    This class runs on a separate thread from workflowRunner,
    launching jobs based on the current state of the TaskDAG
    """
    def _getCommandTaskRunner(self, task) :
        """
        assist launch of a command-task
        """

        # shortcuts:
        payload = task.payload
        param = self._cdata.param

        if payload.cmd.cmd is None :
            # Note these should have been marked off by the TaskManager already:
            raise Exception("Attempting to launch checkpoint task: %s" % (task.fullLabel()))

        isForcedLocal = ((param.mode != "local") and (payload.isForceLocal))

        # mark task resources as occupied:
        if not isForcedLocal :
            if self.freeCores != "unlimited" :
                if (self.freeCores < payload.nCores) :
                    raise Exception("Not enough free cores to launch task")
                self.freeCores -= payload.nCores

            if self.freeMemMb != "unlimited" :
                if (self.freeMemMb < payload.memMb) :
                    raise Exception("Not enough free memory to launch task")
                self.freeMemMb -= payload.memMb

        if payload.mutex is not None :
            self.taskMutexState[payload.mutex] = True

        TaskRunner = None
        if param.mode == "local" or payload.isForceLocal or payload.isCmdMakePath :
            TaskRunner = LocalTaskRunner
        elif param.mode == "sge" :
            TaskRunner = SGETaskRunner
        elif param.mode == "flux" :
            TaskRunner = FluxTaskRunner
        else :
            raise Exception("Can't support mode: '%s'" % (param.mode))

        #
        # TODO: find less hacky way to handle make tasks:
        #
        taskRetry = payload.retry

        if payload.isCmdMakePath :
            taskRetry = copy.deepcopy(payload.retry)
            taskRetry.window = 0

            if param.mode == "local" or payload.isForceLocal :
                launchCmdList = ["make", "-j", str(payload.nCores)]
            elif param.mode == "sge" :
                launchCmdList = siteConfig.getSgeMakePrefix(payload.nCores, payload.memMb, param.schedulerArgList)
            elif param.mode == "flux":
                launchCmdList = siteConfig.getSgeMakePrefix(payload.nCores, payload.memMb, param.schedulerArgList) 
            else :
                raise Exception("Can't support mode: '%s'" % (param.mode))

            launchCmdList.extend(["-C", payload.cmd.cmd])
            payload.launchCmd = Command(launchCmdList, payload.cmd.cwd, payload.cmd.env)

        #
        # each commandTaskRunner requires a unique tmp dir to write
        # wrapper signals to. TaskRunner will create this directory -- it does not bother to destroy it right now:
        #

        # split the task id into two parts to keep from adding too many files to one directory:
        tmpDirId1 = "%03i" % ((int(task.id) / 1000))
        tmpDirId2 = "%03i" % ((int(task.id) % 1000))
        taskRunnerTmpDir = os.path.join(self._cdata.wrapperLogDir, tmpDirId1, tmpDirId2)

        return TaskRunner(task.runStatus, self._cdata.getRunid(),
                          task.fullLabel(), payload.launchCmd,
                          payload.nCores, payload.memMb,
                          taskRetry, param.isDryRun,
                          self._cdata.taskStdoutFile,
                          self._cdata.taskStderrFile,
                          taskRunnerTmpDir,
                          param.schedulerArgList,
                          self._cdata.flowLog,
                          task.setRunstate)


class FluxTaskRunner(SGETaskRunner):


    def getFullCmd(self):
        # qsub options
        #
        qsubCmd = ["qsub",
                 "-V",  # import environment variables from shell
                 "-cwd",  # use current working directory
                 "-S", sys.executable,  # The taskwrapper script is python
                 "-o", self.wrapFile,
                 "-e", self.wrapFile]

        qsubCmd.extend(self.schedulerArgList)
        qsubCmd.extend(siteConfig.qsubResourceArg(self.nCores, self.memMb))
        qsubCmd.extend(self.wrapperCmd)

        print qsubCmd
        sys.exit()
        return tuple(qsubCmd)


class Runner(FluxWorkflowRunner):
    def __init__(self, run_dp, num_cpu):
        self.run_dp = run_dp
        self.num_cpu = num_cpu

    def workflow(self):
        """ method invoked on class instance run call """
        self.addTask("tmp", command=['echo', '"Base Analysis Workflow: Running with a maximum of {} cores"'.format(self.num_cpu)])


@click.command()
@click.argument('run_dp')
@click.option('--flux/--no-flux', default=False)
@click.option('--account', '-a')
@click.option('--ppn', '-p', default=4)
@click.option('--mem', '-m', default='20gb')
@click.option('--walltime', '-w', default='2:00:00')
def runner(run_dp, flux, account, ppn, mem, walltime):
    """ Analysis Workflow Management

    Sets up Pyflow WorkflowRunner and launches locally by default or via flux

    Arguments:
    run_dp -- String path to run directory to use for analysis
    """
    log_output_dp = os.path.join(run_dp, 'bioinfo', 'logs', 'runner')
    workflow_runner = Runner(run_dp=run_dp, num_cpu=ppn)

    if flux:
        workflow_runner.run(mode='flux', dataDirRoot=log_output_dp)

        #full_dp = os.path.dirname(os.path.abspath(__file__))
        #activate = 'source {}'.format(os.path.join(full_dp, 'dependencies', 'miniconda', 'bin', 'activate'))
        #runner_fp = os.path.join(full_dp, 'runner.py')
        #qsub = 'qsub -N omics_16s -A {} -q fluxm -l nodes=1:ppn={},mem={},walltime={}'.format(account, ppn, mem, walltime)
        #call('echo "{} && python {} {}" | {}'.format(activate, runner_fp, run_dp, qsub), shell=True)
    else:
        workflow_runner.run(mode='local', dataDirRoot=log_output_dp)


if __name__ == "__main__":
    runner()
