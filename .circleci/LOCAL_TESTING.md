### circleci_cli.py

circleci_cli.py "wraps" the regular `circleci` command and accepts the same arguments.

```
circleci_cli.py local execute --job jobname
```

Before it starts execution of the actual `circleci` command, it does some preparations, to make local testing possible.
* Converts config file to version - 2.0, because CircleCi CLI can not process 2.1 version configs.
It makes backup of the original file and replace it with 2.0 version. When script finishes, it restores the original config. \
**IMPORTANT: ** Do not change circleci config file while script is running.
 Those changes will be lost when the original config will be restored.
 If something went wrong and the original config file was not restored, just run this script without arguments.
 ```
circleci_cli.py
```

* On job execution with command - `circleci_cli.py local execute --job <jobname>`,
it check `<jobname>` and if it starts with `smoke` it assumes that it is a smoke test
and imports environment variables from `smoke_tests/config.yml`, so you do not have to specify them manually. (see smoke_test/README.md)
* When job is running locally, `docker` commands require root permission, so user for this job is changed to `root`.
 (We can not use `sudo` because job will fail on real CircleCI,
 and we can not add current user to `docker` group due to the same reason)