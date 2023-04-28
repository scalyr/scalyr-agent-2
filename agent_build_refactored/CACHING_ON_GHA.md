# Caching on GitHub Actions Ci/CD

If you want to decrease the building time of something on GitHub Actions, you may
want to consider using `RunnerSteps`

``RunnerSteps`` are wrappers around some shell or Python script. Step can save 
results of their script and those results can be cached for later on Ci/CD. 
This is achieved by tracking all input data that step passes to its script,
and by calculating its cache key or ``id``, which strictly depends on that input 
data. If input data changes, then ``id`` changes too, which leads to invalidation 
of the cache.