$BinName ="test_foucs.c"
clang -g -O1 -fsanitize=fuzzer                         $BinName # Builds the fuzz target w/o sanitizers
clang -g -O1 -fsanitize=fuzzer,address                  $BinName # Builds the fuzz target with ASAN
clang -g -O1 -fsanitize=fuzzer,memory                    $BinName
