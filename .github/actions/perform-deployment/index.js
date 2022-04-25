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
// const child_process = require('child_process')
// const buffer = require('buffer')
// const readline = require('readline')


async function handleStep(
    action,
    stepPath,
    key
) {
    if (action === "upload") {
        const result = await cache.restoreCache([stepPath], key);
        if (result) {
            console.log(`Step ${key} cache has been found.`);
        }
    }
    else {
        try {
            await cache.saveCache([fullPath], cacheKey);
            console.log(`Step ${key} cache has been saved.`);
        } catch (error) {
            console.warn(
                `Can not save cache by key ${cacheKey}. 
                It seems that seems that it has been saved somewhere else.\nOriginal message: ${error.message}`
            )
        }
    }
}

async function performDeployment() {
    // The main action function. It does the following:
    // 1. Get all cache names of the steps of the given deployment and then try to load those caches by using that names.
    // 2. Run the deployment. If there are cache hits that have been done previously, then the deployment will reuse them.
    // 3. If there are deployment steps, which results haven't been found during the step 1, then the results of those
    //    steps will be cached using their cache names.

    const steps_ids_json_str = core.getInput("step-ids-json");
    const cacheVersionSuffix = core.getInput("cache-version-suffix");
    const cacheDir = core.getInput("cache-dir");
    const action = core.getInput("action");

    if (!fs.existsSync(cacheDir)) {
        fs.mkdirSync(cacheDir,{recursive: true});
    }

    const step_ids = JSON.parse(steps_ids_json_str);

    for (let id of step_ids) {
        console.log(id);
        const stepDir = path.join(cacheDir, "step_outputs", id);
        const cacheKey = `${id}-${cacheVersionSuffix}`;
        await handleStep(
            action,
            stepDir,
            cacheKey
        );
    }
}


async function run() {
    // Entry function. Just catch any error and pass it to GH Actions.
  try {
      await performDeployment();
  } catch (error) {
    core.setFailed(error.message);
  }
}

run()

