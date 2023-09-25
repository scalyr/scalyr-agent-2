# Building and Testing Workflows
## Actions Variables

| Name                | Description                                         | Sample                                                                                                         | Default        |
| ------------------- |:---------------------------------------------------:| --------------------------------------------------------------------------------------------------------------:| -------------- |
| ENABLED_BUILDERS    | Builders to use for container images                | [{  "builder_name": "ubuntu",  "base_image":  "ubuntu:22.04", architectures: ["x86_64", "aarch64", "armv7"] }] | None/Mandatory |
| UNIT_TESTS_DISABLED | Skip Unit Tests                                     | true                                                                                                           | ""             |
| K8S_TESTS_DISABLED  | Skip K8S E2E Tests                                  | true                                                                                                           | ""             |
| RUNNER              | Runner used when building and testing docker images | ubuntu-20.04                                                                                                   | None/Mandatory |
