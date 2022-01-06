The deployment is a tool that provides unified, "CI/CD-agnostic" way to perform some set of actions under the target
environment in order to prepare that environment for some further operations (for example package build, testing etc).

#### The problem

Here is an example of the most common usage of the deployments.
Let's say we have to do some tests on GitHub Actions, and those tests require some Python dependencies, so we just 
create a job and run that command:
```
python3 -m pip install -r requirments.txt
```

Then, it would be nice to optimize that part and enable caching for that Python dependencies. In GH Action that can be 
done by the [@actions/cache](https://github.com/actions/cache) actions.

```
- name: Cache python deps.
  uses: actions/cache@v2
  with:
    path: ~/.cache/pip
    key: python-deps-${{ hashFiles('requirments.txt') }}
```

Sometimes things may be more complex, for example, multiple requirement files or there also may be
needed to install/download another files/tools. If we want to cache that too, then we have also to reflect that files
in the GitHub's `cache` action. More files to cache, more files to track in the `cache` action, and it is also impossible
to reuse that outside of the GitHub actions.


#### Deployments usage example
Let's have a look at more complex example and how we can achieve the same results with `Deployments`.

We need to install Python dependencies from two requirement files and we also need to download browser driver for 
Selenuim.

To achieve that we have a Deployment object in the ``agent_build/tools/environment_deployments/deployments.py`` file.

```
EXAMPLE_ENVIRONMENT = Deployment(
    name="example_environment",
    step_classes=[ExampleStep],
)
```

Here we give a name for our new deployment -`example_environment` and also specify steps that deployment has to perform. 
Each step is a child **class** of the `DeploymentStep` base class, and each such class defines some work that has to be 
done in order to perform the step.

In the example we use step class ``ExampleStep``:

``` 

class ExampleStep(deployments.ShellScriptDeploymentStep):
    @property
    def script_path(self) -> pl.Path:
        return _REL_EXAMPLE_DEPLOYMENT_STEPS_PATH / "install-requirements-and-download-webdriver.sh"

    @property
    def _tracked_file_globs(self) -> List[pl.Path]:
        return [
            *super(ExampleStep, self)._tracked_file_globs,
            _REL_EXAMPLE_DEPLOYMENT_STEPS_PATH / "requirements-*.txt",
    ]
```

Here in the example we declare class `ExampleStep` as a child of the `ShellScriptDeploymentStep`
class. The ``ShellScriptDeploymentStep`` base class is a `DeploymentStep` that runs some shell script in order to perform
the step, and the script is specified in its ``script_path`` property method. In our case, the shell script is 
``install-requirements-and-download-webdriver.sh``. The needed requirement files are reflected in the ``tracked_file_globs`` -
another property method, which is the list of paths to the files, that are somehow used in the deployment step.

The script file ``install-requirements-and-download-webdriver.sh`` does the main work of the step, and it can also cache 
some intermediate results by calling special cache functions, which are sourced before the script:

* Restore the cache
    ```
    restore_from_cache <cache_key> <path>
    ```
* Save to cache 
    ```
    save_to_cache <cache_key> <path>
    ```

NOTE: You can find those example files in tests in file ``agent_build/tools/tests/test_deployments.py``

After the deployment and its steps are defined, we can use it in the GitHub Actions.
To do that, we just have to call a local GitHub action `github/actions/perform-deployment`
and pass the name of our deployment as an argument.

```

  - name: Perform the deployment..
    uses: ./.github/actions/perform-deployment
    with:
      deployment-name: "example_environment"
```

The `github/actions/perform-deployment` Github action will perform needed deployment, and it will
also cache all intermediate results that we cache in the shell script.







