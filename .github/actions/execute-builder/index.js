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
const path = require('path');
const child_process = require('child_process');
const buffer = require('buffer');
const readline = require('readline');


async function checkAndGetCache(
    name,
    cacheDir,
    cacheVersionSuffix
) {
    //
    // Check if there is an existing cache for the given step name.
    //
    const cachePath = path.join(cacheDir, name);
    const key = `${name}-${cacheVersionSuffix}`;

    // try to restore the cache.
    const result = await cache.restoreCache([cachePath], key);

    if (typeof result !== "undefined") {
        console.log(`Cache for the step with key ${key} is found.`);
    } else {
        console.log(`Cache for the step with key ${key} is not found.`);
    }

    // Return whether it is a hit or not.
    return result;
}

async function checkAndSaveCache(
    name,
    cacheDir,
    isHit,
    cacheVersionSuffix
) {
    //
    // Save the cache directory for a particular step if it hasn't been saved yet.
    //

    const fullPath = path.join(cacheDir, name);
    const cacheKey = `${name}-${cacheVersionSuffix}`;

    // Skip files. Step cache can be only the directory.
    if (!fs.lstatSync(fullPath).isDirectory()) {
        return;
    }

    // If there's no cache hit, then save directory to the cache now.
    if (isHit) {
        console.log(`Cache for the step with key ${cacheKey} has been hit. Skip saving.`);
    }
    else {
        console.log(`Save cache for the step with key ${cacheKey}.`);

        try {
            await cache.saveCache([fullPath], cacheKey);
        } catch (error) {
            console.warn(
                `Can not save step cache by key ${cacheKey}. 
                It seems that seems that it has been saved somewhere else.\nOriginal message: ${error}`
            );
        }
    }

    // When completed, step can leave a special file 'paths.txt'.
    // This file contains paths of the tools that are needed to be added to the system's PATH.
    const pathsFilePath = path.join(fullPath, "paths.txt");
    if (fs.existsSync(pathsFilePath)) {

        const lineReader = readline.createInterface({
            input: fs.createReadStream(pathsFilePath)
        });

        lineReader.on('line', function (line) {
            console.log(`Add path ${line}.`);
            core.addPath(line);
        });
    }
}

async function executeBuilder() {

    // The main action function. It does the following:
    // 1. Get all ids of the steps of the given runner and then try to load their caches by using that ids.
    // 2. Execute the runner. If there are cache hits that have been done previously, reuse them.
    // 3. If there are steps, which results haven't been found during the step 1, then the results of those
    //    steps will be cached using their ids.

    const builderName = core.getInput("builder-name");
    const cacheVersionSuffix = core.getInput("cache-version-suffix");
    const buildRootDir = core.getInput("build-root-dir");

    if (!fs.existsSync(buildRootDir)) {
        fs.mkdirSync(buildRootDir,{recursive: true});
    }

    const cacheDir = path.join(buildRootDir, "step_outputs");

    // Get json list with names of all steps which are needed for this runner.
    const executeStepsRunnerScriptPath = path.join(".github", "actions", "execute-builder", "helper.py");
    // Run special github-related helper command which returns names for ids of all steps, which are used in the current
    // runner.
    console.log("RUUN");
    const output = child_process.execFileSync(
        "python3",
        [executeStepsRunnerScriptPath, builderName, "get-cacheable-steps-ids"]
    );
    console.log("RUUN2");
    // Read and decode names from json.
    const json_encoded_step_ids = buffer.Buffer.from(output, 'utf8').toString();
    const steps_ids = JSON.parse(json_encoded_step_ids);

    const cacheHits = {};

    // Run through steps ids and look if the is any existing cache for them.
    for (let id of steps_ids) {
        console.log(id);
        cacheHits[id] = await checkAndGetCache(
            id,
            cacheDir,
            cacheVersionSuffix
        );
    }
    console.log("RUUN3");

    // Run the step. Also provide cache directory, if there are some found caches, then the step
    // has to reuse them.
    child_process.execFileSync(
        "python3",
        [executeStepsRunnerScriptPath, builderName, "execute", "--build-root-dir", buildRootDir],
        {stdio: 'inherit'}
    );

    console.log("RUUN4");

    // Run through the cache folder and save any cached directory within, that is not yet cached.
    //const filenames = fs.readdirSync(finalCacheDir);
    //for (const name of filenames) {
    for (let id of steps_ids) {
        console.log(id);
        await checkAndSaveCache(
            id,
            cacheDir,
            cacheHits[steps_ids],
            cacheVersionSuffix,
        );
    }
        console.log("RUUN5");
}


async function run() {
    // Entry function. Just catch any error and pass it to GH Actions.
  try {
      console.log('HELLO');
      await executeBuilder();
      console.log('BYE');
  } catch (error) {
    core.setFailed(error.message);
  }
}

run();

