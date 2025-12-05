ab -n 100 -c 5 -H "Authorization: Bearer dev-token-123" -p payload.json -T application/json http://localhost:8000/api/generate-copy

: << 'COMMENT_BLOCK_START'
This is ApacheBench, Version 2.3 <$Revision: 1913912 $>
Copyright 1996 Adam Twiss, Zeus Technology Ltd, http://www.zeustech.net/
Licensed to The Apache Software Foundation, http://www.apache.org/

Benchmarking localhost (be patient).....done


Server Software:        uvicorn
Server Hostname:        localhost
Server Port:            8000

Document Path:          /api/generate-copy
Document Length:        47 bytes

Concurrency Level:      5
Time taken for tests:   0.053 seconds
Complete requests:      100
Failed requests:        95
   (Connect: 0, Receive: 0, Length: 95, Exceptions: 0)
Non-2xx responses:      95
Total transferred:      20905 bytes
Total body sent:        27900
HTML transferred:       5080 bytes
Requests per second:    1887.61 [#/sec] (mean)
Time per request:       2.649 [ms] (mean)
Time per request:       0.530 [ms] (mean, across all concurrent requests)
Transfer rate:          385.36 [Kbytes/sec] received
                        514.30 kb/s sent
                        899.66 kb/s total

Connection Times (ms)
              min  mean[+/-sd] median   max
Connect:        0    0   0.2      0       1
Processing:     1    2   0.6      2       5
Waiting:        1    2   0.5      2       5
Total:          2    2   0.6      2       5

Percentage of the requests served within a certain time (ms)
  50%      2
  66%      2
  75%      3
  80%      3
  90%      3
  95%      3
  98%      4
  99%      5
 100%      5 (longest request)

COMMENT_BLOCK_END'