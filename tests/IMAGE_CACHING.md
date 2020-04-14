Some of the tests cases (for example package and monitor tests) are decorated with special function
`dockerized_case` from `tests/utils/dockerized.py`.
This means this cases are meant to be executed in special docker container
to provide particular environment which is needed for test.

If test case is decorated, it does not run directly but builds an image by one of the "image builder" classes
that are defined in `/tests/image_builder` directory.
All image builders are subclasses of the base `AgentImageBuilder` class (see `tests/utils/image_builder`).
One of such classes should be passed to decorator as a first argument.
The second argument is a path to the file where tests case is located,
because we need to run the same test file inside the container.
```
import tests.utils.dockerized

@dockerized.dockerized_case(ImageBuilderClass, __file__)
def test_case():
    ...
```



### Image caching.

In some scenarios (for example: in CircleCi jobs) the current platform does not provide docker image build caching
and image build process has to be done from scratch on every iteration.
To bypass this, the next command can be used.

```
python /tests/image_builder/<path_to_particulat_bulder>/cmd.py --build-with-cache <image output directory path>
```

The `cmd.py` is a file that acts like command line script and it can be created for each image builder.
The `--build-with-cache`option it a path to cache directory. When it is specified there are two possible cases:
1) Image file is not presented inside this cache directory and image has to be built from scratch,
after that, the new image is saved to the cache directory for future use.
2) Image file is presented inside cache directory (in other words the first step has already happened earlier),
so it just reused without building.

