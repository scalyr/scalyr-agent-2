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
const process = require('process')


async function checkAndGetCache(
    name,
    cacheDir,
    finalCacheSuffix
) {
    //
    // Check if there is an existing cache for the given step name.
    //
    const cachePath = path.join(cacheDir, name)
    const key = `${name}-${finalCacheSuffix}`

    // try to restore the cache.
    const result = await cache.restoreCache([cachePath], key)

    if (typeof result !== "undefined") {
        console.log(`Cache for the step with key ${key} is found.`)
    } else {
        console.log(`Cache for the step with key ${key} is not found.`)
    }

    // Return whether it is a hit or not.
    return result
}

async function checkAndSaveCache(
    name,
    cacheDir,
    isHit,
    finalCacheSuffix
) {
    //
    // Save the cache directory for a particular step if it hasn't been saved yet.
    //

    const fullPath = path.join(cacheDir, name)
    const cacheKey = `${name}-${finalCacheSuffix}`

    // Skip files. Cache can be only the directory.
    if (!fs.lstatSync(fullPath).isDirectory()) {
        console.log(`File ${fullPath} is skipped.`)
        return
    }

    // If there's no cache hit, then save directory to the cache now.
    if (isHit) {
        console.log(`Step cache with key ${cacheKey} already exist, skip saving.`)
    }
    else {
        console.log(`Save cache for the step with key ${cacheKey}.`)

        try {
            await cache.saveCache([fullPath], cacheKey)
        } catch (error) {
            console.log(
            `Cache with key ${cacheKey} should have been already saved by another job, skip.\nOriginal message: ${error}`
            )
        }
    }

    // The step can leave a special file 'paths.txt'.
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

async function executeRunner() {
    // The main action function. It does the following:
    // 1. Get all cache names of the steps of the given runner and then try to load those caches by using that names.
    // 2. Execute the runner. If there are cache hits that have been done previously, then the runner will reuse them.
    // 3. If there are steps, which results haven't been found during the step 1, then the results of those
    //    steps will be cached using their cache names.

    const runnerFQDN = core.getInput("runner-fqdn");
    const cacheVersionSuffix = core.getInput("cache-version-suffix");
    const cacheDir = path.resolve(path.join("agent_build_output", "step_cache"));
    const cacheKeyRunnerPart = core.getInput("cache-key-runner-part")
    if (!fs.existsSync(cacheDir)) {
        fs.mkdirSync(cacheDir,{recursive: true})
    }

    // Get json list with names of all steps which are needed for this runner.
    const runner_helper_script_path = path.join("agent_build_refactored", "scripts", "runner_helper.py")
    // Run special github-related helper command which returns names for all steps, which are used in the current
    // runner.
    const code = child_process.execFileSync(
        "python3",
        [runner_helper_script_path, runnerFQDN, "--get-all-cacheable-steps"]
    );

    // Read and decode names from json.
    const json_encoded_step_names = buffer.Buffer.from(code, 'utf8').toString()
    const step_cache_names = JSON.parse(json_encoded_step_names)

    const cacheHits = {}

    const finalCacheSuffix = `${cacheKeyRunnerPart}-${cacheVersionSuffix}`

    // Run through step names and look if the is any existing cache for them.
    console.log("Restoring steps caches.");
    for (let name of step_cache_names) {
        console.log(`Check cache for step ${name}`);
        cacheHits[name] = await checkAndGetCache(
            name,
            cacheDir,
            finalCacheSuffix
        )
    }

    // Execute runner's steps. Also provide cache directory, if there are some found caches, then the step
    // has to reuse them.
    const env = JSON.parse(JSON.stringify(process.env));
    env["AWS_ENV_VARS_PREFIX"] = "INPUT_"
    child_process.execFileSync(
        "python3",
        [runner_helper_script_path, runnerFQDN, "--run-all-cacheable-steps"],
        {stdio: 'inherit', env: env}
    );

    // Run through the cache folder and save any cached directory within, that is not yet cached.
    console.log("Saving step caches.");
    const filenames = fs.readdirSync(cacheDir);
    for (const name of filenames) {
        console.log(`Save cache for step ${name}`);
        await checkAndSaveCache(
            name,
            cacheDir,
            cacheHits[name],
            finalCacheSuffix,
        )
    }
}


async function run() {
    // Entry function. Just catch any error and pass it to GH Actions.
  try {
      await executeRunner()
  } catch (error) {
    core.setFailed(error.message);
  }
}

run()

