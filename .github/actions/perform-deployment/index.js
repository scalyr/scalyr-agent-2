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


async function checkAndGetCache(
    name,
    cacheDir,
    cacheVersionSuffix
) {
    //
    // Check if there is an existing cache for the given deployment step name.
    //
    const cachePath = path.join(cacheDir, name)
    const key = `${name}-${cacheVersionSuffix}`

    // try to restore the cache.
    const result = await cache.restoreCache([cachePath], key)

    if (typeof result !== "undefined") {
        console.log(`Cache for the deployment step with key ${key} is found.`)
    } else {
        console.log(`Cache for the deployment step with key ${key} is not found.`)
    }

    // Return whether it is a hit or not.
    return result
}

async function checkAndSaveCache(
    name,
    cacheDir,
    isHit,
    cacheVersionSuffix
) {
    //
    // Save the cache directory for a particular deployment step if it hasn't been saved yet.
    //

    const fullPath = path.join(cacheDir, name)
    const cacheKey = `${name}-${cacheVersionSuffix}`

    // Skip files. Deployment cache can be only the directory.
    if (!fs.lstatSync(fullPath).isDirectory()) {
        return
    }

    // If there's no cache hit, then save directory to the cache now.
    if (isHit) {
        console.log(`Cache for the deployment step with key ${cacheKey} has been hit. Skip saving.`)
    }
    else {
        console.log(`Save cache for the deployment step with key ${cacheKey}.`)

        try {
            await cache.saveCache([fullPath], cacheKey)
        } catch (error) {
            console.warn(
                `Can not save deployment cache by key ${cacheKey}. 
                It seems that seems that it has been saved somewhere else.\nOriginal message: ${error}`
            )
        }
    }

    // After the deployment, the deployment can leave a special file 'paths.txt'.
    // This file contains paths of the tools that are needed to be added to the system's PATH.
    const pathsFilePath = path.join(fullPath, "paths.txt")
    if (fs.existsSync(pathsFilePath)) {

        const lineReader = readline.createInterface({
            input: fs.createReadStream(pathsFilePath)
        });

        lineReader.on('line', function (line) {
            console.log(`Add path ${line}.`);
            core.addPath(line)
        });
    }
}

async function performDeployment() {
    // The main action function. It does the following:
    // 1. Get all cache names of the steps of the given deployment and then try to load those caches by using that names.
    // 2. Run the deployment. If there are cache hits that have been done previously, then the deployment will reuse them.
    // 3. If there are deployment steps, which results haven't been found during the step 1, then the results of those
    //    steps will be cached using their cache names.

    const deploymentName = core.getInput("deployment-name")
    const cacheVersionSuffix = core.getInput("cache-version-suffix")
    const cacheDir = path.resolve(path.join("agent_build_output", "deployment_cache", deploymentName))

    if (!fs.existsSync(cacheDir)) {
        fs.mkdirSync(cacheDir,{recursive: true})
    }

    // Get json list with names of all deployments which are needed for this deployment.
    const deployment_helper_script_path = path.join("agent_build", "scripts", "run_deployment.py")
    // Run special github-related helper command which returns names for all deployments, which are used in the current
    // deployment.
    const code = child_process.execFileSync(
        "python3",
        [deployment_helper_script_path, "deployment", deploymentName, "get-deployment-all-cache-names"]
    );

    // Read and decode names from json.
    const json_encoded_deployment_names = buffer.Buffer.from(code, 'utf8').toString()
    const deployment_cache_names = JSON.parse(json_encoded_deployment_names)

    const cacheHits = {}

    // Run through deployment names and look if the is any existing cache for them.
    for (let name of deployment_cache_names) {
        cacheHits[name] = await checkAndGetCache(
            name,
            cacheDir,
            cacheVersionSuffix
        )
    }

    // Run the deployment. Also provide cache directory, if there are some found caches, then the deployment
    // has to reuse them.
    child_process.execFileSync(
        "python3",
        [deployment_helper_script_path, "deployment", deploymentName, "deploy"],
        {stdio: 'inherit'}
    );

    // Run through the cache folder and save any cached directory within, that is not yet cached.
    const filenames = fs.readdirSync(cacheDir);
    for (const name of filenames) {
        await checkAndSaveCache(
            name,
            cacheDir,
            cacheHits[name],
            cacheVersionSuffix,
        )
    }
}


async function run() {
    // Entry function. Just catch any error and pass it to GH Actions.
  try {
      await performDeployment()
  } catch (error) {
    core.setFailed(error.message);
  }
}

run()

