# SysecLibFuzzer
Extension 1)
multi_foucs_function Fuzzing:-
An extension of LibFuzzer. Currently supports a new fuzzing flag --foucs_functions, which extends a single function-aware fuzzing into fuzzing many functions at once. 
The goal is to generate fuzzing tests around locations that are known to trigger crashes/bugs. The flags are still under testing 

(works for small fuzz harness, and porting to an OSS-Fuzz discovered bugs is: ``in progress``)  


Extension 2) 
Path-aware focus functions:-
(in-progress) The goal is to ensure that abstracted crashes are fuzzed based on a signature path, to facilitate similar tests related to the fuzzer, and to ensure that the tracing comparison is accurate.


Extension 3) 
Hooks/Callbacks to monitor values
This should use the existing hooks of LLVM sanitizers or LLVM IR to view "Limited values" as run time(this must be added in a smart way to only instrument specific functions)
Additionally, this will serve as a replacement for DAWRF-like tools if they fail to port to ARVO. 
(Post-extension 2)

