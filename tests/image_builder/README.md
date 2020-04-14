This directory contains image builder - statically defined abstractions that help to build images for tests.

The structure:

* `__init__.py`:
Image builder is declared there. It should be a subclass of the `tests.utils.image_builder.AgentImageBuilder` class.

* `cmd.py`:
Script that supposed to be executed as script file, if there is need to build image from command line,
for example, to pre-build it and to save in cache in CI systems.

* Also directory can contain Dockerfiles for each image defined there.
