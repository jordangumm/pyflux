import os, sys
import click

from pyflux.pyflux import FluxWorkflowRunner
from subprocess import call


class Runner(FluxWorkflowRunner):
    def __init__(self, run_dp, num_cpu):
        self.run_dp = run_dp
        self.num_cpu = num_cpu

    def workflow(self):
        """ method invoked on class instance run call """
        self.addTask("echo", command=['echo', '"Base Analysis Workflow: Running with a maximum of {} cores"'.format(self.num_cpu)])


@click.command()
@click.argument('run_dp')
@click.option('--flux/--no-flux', default=False)
@click.option('--dispatch/--no-dispatch', default=True)
@click.option('--account', '-a')
@click.option('--ppn', '-p', default=4)
@click.option('--mem', '-m', default='20000') # current limitation, only handles mb
@click.option('--walltime', '-w', default='2:00:00')
def runner(run_dp, flux, dispatch, account, ppn, mem, walltime):
    """ Analysis Workflow Management

    Sets up Pyflow WorkflowRunner and launches locally by default or via flux

    Arguments:
    run_dp -- String path to run directory to use for analysis
    """
    log_output_dp = os.path.join(run_dp, 'bioinfo', 'logs', 'runner')
    workflow_runner = Runner(run_dp=run_dp, num_cpu=ppn)

    if flux:
        if not account: sys.exit('To attempt a submission to the flux cluster you need to supply an --account/-a')
        if dispatch:
            full_dp = os.path.dirname(os.path.abspath(__file__))
            activate = 'source {}'.format(os.path.join(full_dp, 'dependencies', 'miniconda', 'bin', 'activate'))
            runner_fp = os.path.join(full_dp, 'runner.py')
            qsub = 'qsub -N pyflux_handler -A {} -q fluxm -l nodes=1:ppn=1,mem=2000mb,walltime={}'.format(account, walltime)
            call('echo "{} && python {} {} --flux --no-dispatch --account {}" | {}'.format(activate, runner_fp,
                                                                                           run_dp, account, qsub), shell=True)
        else:
            workflow_runner.run(mode='flux', dataDirRoot=log_output_dp, nCores=ppn, memMb=mem,
                                schedulerArgList=['-N', 'pyflux_runner',
                                                  '-A', account,
                                                  '-l', 'nodes=1:ppn={},mem={}mb,walltime={}'.format(ppn, mem, walltime)])
    else:
        workflow_runner.run(mode='local', dataDirRoot=log_output_dp, nCores=ppn, memMb=mem)


if __name__ == "__main__":
    runner()
