This action uses python module `agent_build/tools/environment_deployments.py`
to perform some deployment which is defined in it. The main purpose of the action is to
cache results of this deployment to the GitHub Actions cache. Since the deployments consist of 
steps, and different deployments can use the same step, then it's more reasonable to cache each step
separately. That means that the regular [@actions/cache](https://github.com/actions/cache) 
is not enough, and we need to use more flexible JS scripting to call GitHub Actions caching dynamically.

See more about: 
* Creating GitHub Action using JS: https://docs.github.com/en/actions/creating-actions/creating-a-javascript-action
* Using GitHub Actions @actions/cache JS library: https://github.com/actions/toolkit/tree/main/packages/cache


### Add changes and apply them to the repository.

Before starting, make sure you have Node.js installed.

Then:
    
1. `cd ` to the directory of the action.
2. Install the dependencies of the action.
```
npm install
```
3. Make all needed changes.
4. Before committing the changes, compile the `index.js` and all its dependencies into one file.
To do that you need to install library `@vercel/ncc`
   ```
   npm i -g @vercel/ncc
   ```
   After that, compile the code by running:
   ```
   ncc build index.js
   ```
   That has to compile all needed code and put it into the `dist` folder in the same directory, 
   which also has to be committed to the repository. GitHub Actions requires to commit the `node_modules`,
   that's why the alternative with `ncc` seems more compact.
   

5. Commit changes.