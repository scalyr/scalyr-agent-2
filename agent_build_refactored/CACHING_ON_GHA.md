# Caching on GitHub Actions Ci/CD

If you want to decrease the building time of something on GitHub Actions, you may
want to consider using `RunnerSteps`

``RunnerSteps`` are wrappers around some shell or Python script. Step can save 
results of their script and those results can be cached for later on Ci/CD. 
This is achieved by tracking all input data that step passes to its script,
and by calculating its cache key or ``id``, which strictly depends on that input 
data. If input data changes, then ``id`` changes too, which leads to invalidation 
of the cache.

There two types of RunnerSteps:
1. ``EnvironmentRunnerStep`` - runs its script to make changes on the environment where it runs.
As an example, look at the ``INSTALL_TEST_REQUIREMENT_STEP`` step instance in module 
``agent_build_refactored/__init__.py`` it uses script ``agent_build_refactored/scripts/steps/deploy-test-environment.sh``
which installs Python libraries from pip. Script uses special functions such
``restore_from_cache`` and ``save_to_cache`` to cache downloaded Python libraries by caching pip's cache folder.

2. ``ArtifactRunnerStep`` - this step, as name implies, produces some artifact as a result of it work.

Every ``RunnerStep`` has to be a part of the ``Runner`` class. ``Runner`` is class that runs some 
code to perform its work.