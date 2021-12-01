// Copyright 2014-2021 Scalyr Inc.
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//   http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

const core = require('@actions/core');
const cache = require('@actions/cache');
const fs = require('fs');
const path = require('path')
const child_process = require('child_process')
const buffer = require('buffer')
const readline = require('readline')


async function run() {
  try {
    const deploymentName = core.getInput("deployment-name")
    const cacheVersionSuffix = core.getInput("cache-version-suffix")
    const cacheDir = "deployment_caches"

    // Get json list with names of all deployments which are needed for this deployment.
    const deployment_helper_script_path = path.join("agent_build" ,"scripts", "run_deployment.py")
    // Run special github-related helper command which returns names for all deployments, which are used in the current
    // deployment.
    const code = child_process.execFileSync(
        "python3",
        [deployment_helper_script_path, "deployment", deploymentName, "get-deployment-all-cache-names"]
    );

    // Read and decode names from json.
    const json_encoded_deployment_names = buffer.Buffer.from(code, 'utf8').toString()
    const deployer_cache_names = JSON.parse(json_encoded_deployment_names)

    const cache_hits = {}

    // Run through deployment names and look if the is any existing cache for them.
    for (let name of deployer_cache_names) {

        const cache_path = path.join(cacheDir, name)
        const key = `${name}-${cacheVersionSuffix}`

        // try to restore the cache.
        const result = await cache.restoreCache([cache_path], key)

        if(typeof result !== "undefined") {
          console.log(`Cache for the deployment ${name} is found.`)
        } else {
          console.log(`Cache for the deployment ${name} is not found.`)
        }
        cache_hits[name] = result

    }

    // Run the deployment. Also provide cache directory, if there are some found caches, then the deployer
    // has to reuse them.
    child_process.execFileSync(
        "python3",
        [deployment_helper_script_path, "deployment", deploymentName, "deploy", "--cache-dir", cacheDir],
        {stdio: 'inherit'}
    );

    if ( fs.existsSync(cacheDir)) {
      console.log("Cache directory is found.")

      // Run through the cache folder and save any cached directory within, that is not yet cached.
      const filenames = fs.readdirSync(cacheDir);
      for (const name of filenames) {

        const full_child_path = path.join(cacheDir, name)

        // Skip files. Deployment cache can be only the directory.
        if (fs.lstatSync(full_child_path).isDirectory()) {

          const key = `${name}-${cacheVersionSuffix}`

          if ( ! cache_hits[name] ) {
            console.log(`Save cache for the deployment ${name}.`)
            try {
              await cache.saveCache([full_child_path], key)
            } catch (error) {

              console.warn(`Can not save deployment cache by key ${key}. It seems that seesm that it has been
               saved somewhere else.\nOriginal message: ${error}`)
            }
          } else {
            console.log(`Cache for the deployment ${name} has been hit. Skip saving.`)
          }

          // After the deployment, the deployer can leave a special file 'paths.txt'.
          // This file contains paths of the tools that are needed to be added to the system's PATH.
          const paths_file_path = path.join(full_child_path, "paths.txt")
          if (fs.existsSync(paths_file_path)) {

            var lineReader = readline.createInterface({
              input: fs.createReadStream(paths_file_path)
            });

            lineReader.on('line', function (line) {
              console.log('Line from file:', line);
              core.addPath(line)
            });
          }
        }
      }
    } else {
      console.warn("Cache directory is not found.")
    }
  } catch (error) {
    core.setFailed(error.message);
  }
}

run()

