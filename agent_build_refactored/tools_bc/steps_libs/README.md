This is a special package where we store pieces of code that are used in 
RunnerSteps. 

Since we track and invalidate step's cache by calculating its 
checksum, it's important to track as little dependency modules as possible,
so if we change some dependency modules, that changes won't affect steps which 
are not really use that modules.