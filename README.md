# Pyflux
A [pyFlow](https://github.com/Illumina/pyflow) extension for automating distributed workflows on the [UofM Flux cluster](http://arc-ts.umich.edu/systems-services/flux/).  At the moment it's basically a skeleton for building workflows, but I might make it into a python package if there's enough interest or if it seems useful enough.

Everything from the [pyFlow](http://illumina.github.io/pyflow/) docs should apply.

Built and tested on GNU/Linux.

## Setup
```
$ pip install -r requirements.txt
```

## Template Usage
Make sure you're logged into your flux account and have already set up the repo.

### Local Run
```
$ python runner.py
```

### Flux Run
```
$ python runner.py --flux -a [account/allocation_name]
```

## Things to watch out for
You can set core and memory requirements for tasks via the [addTask](http://illumina.github.io/pyflow/WorkflowRunner_API_html_doc/index.html) method, but make sure you coordinate that information with the task being distributed.

For example, if you designate a task with 4 cores and 16Gb of RAM but dispatch a command that takes up more space your job will be killed by Flux.  Sometimes resource usage is difficult to estimate, so overshoot and optimize if it's worth it in the long term.  Personally, there are only a few steps that I've fully optimized for my metagenomics workflows (QC, Assembly, Binning).
