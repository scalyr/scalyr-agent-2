# Building and Testing Workflows
## Actions Variables

| Name                | Description                                         | Sample                                                                                                         | Default        |
| ------------------- |:---------------------------------------------------:| --------------------------------------------------------------------------------------------------------------:| -------------- |
| ENABLED_BUILDERS    | Builders to use for container images                | [{  "builder_name": "ubuntu",  "base_image":  "ubuntu:22.04", architectures: ["x86_64", "aarch64", "armv7"] }] | None/Mandatory |
| UNIT_TESTS_DISABLED | Skip Unit Tests. Usually used for speeding up checks and builds not related to changes in unit tested parts of code, i.e. releasing a new version, debugging a GHA workflow.  | true                                                                                                           | ""             |
| K8S_TESTS_DISABLED  | Skip K8S E2E Tests. Usually used for speeding up checks and builds not related to changes in K8S parts of code, i.e. releasing a new version, debugging a GHA workflow      | true                                                                                                           | ""             |
| RUNNER              | Runner used when building and testing docker images | ubuntu-20.04                                                                                                   | None/Mandatory |
