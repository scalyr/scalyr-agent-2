## Builders.

Each type of the agent distribution has to be built by a particular builder that is defined in the ``agent_builders`` 
module. Basically those builders are subclasses of the `Builder` abstract class in the  ``tools.builder`` module, 
and the build process has to be performed in its overridden ``_run`` method. All builders have to have a project-wide 
unique name, so it can be easily executed by using the ``build_package_new.py`` script with specified builder name.

For example:
```shell
python3 build_package_new.py docker-json-debian
```

Some parts of the build can be moved to a separate `BuilderStep` in order to be performed in another environment or be 
cached on CI/CD. A builder step can be created by subclassing the ``BuilderStep`` class in the ``tools/builder`` module.
Instances of such steps has to be specified 

