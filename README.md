# SysecLibFuzzer
Extension 1)

multi_foucs_function Fuzzing:-
An extension of LibFuzzer. Currently supports a new fuzzing flag --foucs_functions, which extends a single function-aware fuzzing into fuzzing many functions at once. 
The goal is to generate fuzzing tests targeting locations known to trigger crashes/bugs. The flags are still under testing 
Update: ported well into ARVO (libxml2). The Flags seem stable, but it's not clear how accurate they are. 
This needs further investigation, ensuring that the flags and the path-aware fuzzing are functional 
(works for small fuzz harness, and porting to an OSS-Fuzz discovered bugs is: ~~``in progress``~~) 


Extension 2 updated) 
Path-aware focus functions:-
(~~in-progress~~)(``updated: added but not tested``) The goal is to ensure that abstracted crashes are fuzzed based on a signature path, to facilitate similar tests related to the fuzzer, and to ensure that the tracing comparison is accurate.
This extension needs to be tested; so far, it's unclear whether it works. Full details about how the path works will be added shortly, but simply put, the approach is to extend the -focus_functions and use the provided symbols to track the depth of path execution, with a limit of 10 paths. Finally, (needs some work): runtime hooks to ensure that the location of where the execution must be restored for now, to avoid possible complexities of adding binary re-writing, both static and at runtime, we added a flag to ensure we keep track of the crash point vividly (this needs to be improved later. 
The goal is to restore the point of divergence by performing additional runtime binary rewriting and injecting hooks that it's calling, so we can start observing from here. 

Extension 3) 
Hooks/Callbacks to monitor values. (Using DAWRF is too intense, and in theory, this direction should only aim for args, function entry, and exit; however, extension 2 should shortcut this "if it works.")
This should use the existing hooks of LLVM sanitizers or LLVM IR to view "Limited values" as run time(this must be added in a smart way to only instrument specific functions)
Additionally, this will serve as a replacement for DAWRF-like tools if they fail to port to ARVO. 
(Post-extension 2)


Testing) 
There's a folder called custom_tests. The goal is to add test cases to ensure the new extension is thoroughly tested.

Binary rewriting) For now, only runtime hooks are the ``untested`` approach. If that fails, using e9path or pin to log one key location, the starting point of the function execution, we can use that to only perform analysis at that location to bypass the gap of sanitizers' abstractions. (require recompiling, which is not ideal)

