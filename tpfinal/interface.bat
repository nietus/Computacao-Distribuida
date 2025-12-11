@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1
title Skin IA - Distributed System Tester

:MENU
cls
echo ╔════════════════════════════════════════════════════════════╗
echo ║       SKIN IA - DISTRIBUTED SYSTEM TESTER                  ║
echo ╠════════════════════════════════════════════════════════════╣
echo ║                                                            ║
echo ║   [1] Check System Status (All Nodes)                      ║
echo ║   [2] Check Leader Info                                    ║
echo ║   [3] Analyze Single Image (bcp8.jpg)                      ║
echo ║   [4] Analyze Single Image (sebks23.jpg)                   ║
echo ║   [5] RAPID FIRE - Send 6 Images Fast!                     ║
echo ║   [6] Trigger Manual Election                              ║
echo ║   [7] Check Specific Task Status                           ║
echo ║   [8] View Node Health Summary                             ║
echo ║   [9] Stress Test (10 requests)                            ║
echo ║                                                            ║
echo ║   === CHAOS TESTING ===                                    ║
echo ║   [A] KILL LEADER - Watch election happen!                 ║
echo ║   [B] KILL NODE 1 - Test fault tolerance                   ║
echo ║   [C] KILL NODE 2 - Test fault tolerance                   ║
echo ║   [D] RESTART ALL NODES                                    ║
echo ║   [E] CHAOS MODE - Kill leader during requests!            ║
echo ║                                                            ║
echo ║   [0] Exit                                                 ║
echo ║                                                            ║
echo ╚════════════════════════════════════════════════════════════╝
echo.
set /p choice="Select option: "

if "%choice%"=="1" goto STATUS
if "%choice%"=="2" goto LEADER
if "%choice%"=="3" goto ANALYZE1
if "%choice%"=="4" goto ANALYZE2
if "%choice%"=="5" goto RAPIDFIRE
if "%choice%"=="6" goto ELECTION
if "%choice%"=="7" goto TASKSTATUS
if "%choice%"=="8" goto HEALTH
if "%choice%"=="9" goto STRESS
if /i "%choice%"=="A" goto KILLLEADER
if /i "%choice%"=="B" goto KILLNODE1
if /i "%choice%"=="C" goto KILLNODE2
if /i "%choice%"=="D" goto RESTARTALL
if /i "%choice%"=="E" goto CHAOS
if "%choice%"=="0" goto EXIT
goto MENU

:STATUS
cls
echo ============================================================
echo                    DISTRIBUTED SYSTEM STATUS
echo ============================================================
echo.
echo --- NODE 1 (Port 8001) ---
curl -s http://localhost:8001/v1/distributed/status 2>nul
echo.
echo.
echo --- NODE 2 (Port 8002) ---
curl -s http://localhost:8002/v1/distributed/status 2>nul
echo.
echo.
echo --- NODE 3 (Port 8003) ---
curl -s http://localhost:8003/v1/distributed/status 2>nul
echo.
echo.
pause
goto MENU

:LEADER
cls
echo ============================================================
echo                      LEADER INFORMATION
echo ============================================================
echo.
curl -s http://localhost:80/v1/distributed/leader 2>nul
echo.
echo.
pause
goto MENU

:ANALYZE1
cls
echo ============================================================
echo              ANALYZING IMAGE: bcp8.jpg
echo ============================================================
echo.
echo Submitting image to distributed system...
echo.
curl -s -X POST -F "file=@img/bcp8.jpg" http://localhost:80/v1/analyze 2>nul > temp_resp.json
type temp_resp.json
echo.
echo.
echo Extracting request_id...
for /f "tokens=*" %%a in ('python -c "import json; print(json.load(open('temp_resp.json'))['request_id'])"') do set reqid=%%a
echo Request ID: %reqid%
del temp_resp.json 2>nul
echo.
echo Waiting 10 seconds for processing...
timeout /t 10 /nobreak >nul
echo.
echo --- RESULT ---
curl -s http://localhost:80/v1/status/%reqid% 2>nul
echo.
echo.
pause
goto MENU

:ANALYZE2
cls
echo ============================================================
echo              ANALYZING IMAGE: sebks23.jpg
echo ============================================================
echo.
echo Submitting image to distributed system...
echo.
curl -s -X POST -F "file=@img/sebks23.jpg" http://localhost:80/v1/analyze 2>nul > temp_resp.json
type temp_resp.json
echo.
echo.
echo Extracting request_id...
for /f "tokens=*" %%a in ('python -c "import json; print(json.load(open('temp_resp.json'))['request_id'])"') do set reqid=%%a
echo Request ID: %reqid%
del temp_resp.json 2>nul
echo.
echo Waiting 10 seconds for processing...
timeout /t 10 /nobreak >nul
echo.
echo --- RESULT ---
curl -s http://localhost:80/v1/status/%reqid% 2>nul
echo.
echo.
pause
goto MENU

:RAPIDFIRE
cls
echo ============================================================
echo              RAPID FIRE TEST - 6 IMAGES
echo ============================================================
echo.
echo Firing 6 image analysis requests in quick succession...
echo Watch how the leader distributes tasks across nodes!
echo.

echo [1/6] Sending bcp8.jpg...
for /f "delims=" %%i in ('curl -s -X POST -F "file=@img/bcp8.jpg" http://localhost:80/v1/analyze 2^>nul') do set resp1=%%i
echo %resp1%
echo.

echo [2/6] Sending sebks23.jpg...
for /f "delims=" %%i in ('curl -s -X POST -F "file=@img/sebks23.jpg" http://localhost:80/v1/analyze 2^>nul') do set resp2=%%i
echo %resp2%
echo.

echo [3/6] Sending bcp8.jpg...
for /f "delims=" %%i in ('curl -s -X POST -F "file=@img/bcp8.jpg" http://localhost:80/v1/analyze 2^>nul') do set resp3=%%i
echo %resp3%
echo.

echo [4/6] Sending sebks23.jpg...
for /f "delims=" %%i in ('curl -s -X POST -F "file=@img/sebks23.jpg" http://localhost:80/v1/analyze 2^>nul') do set resp4=%%i
echo %resp4%
echo.

echo [5/6] Sending bcp8.jpg...
for /f "delims=" %%i in ('curl -s -X POST -F "file=@img/bcp8.jpg" http://localhost:80/v1/analyze 2^>nul') do set resp5=%%i
echo %resp5%
echo.

echo [6/6] Sending sebks23.jpg...
for /f "delims=" %%i in ('curl -s -X POST -F "file=@img/sebks23.jpg" http://localhost:80/v1/analyze 2^>nul') do set resp6=%%i
echo %resp6%
echo.

echo ============================================================
echo Waiting 30 seconds for all tasks to complete...
timeout /t 30 /nobreak
echo.
echo ============================================================
echo                    NODE STATISTICS
echo ============================================================
echo.
echo --- NODE 1 ---
curl -s http://localhost:8001/v1/distributed/status 2>nul | findstr /i "tasks_processed"
echo.
echo --- NODE 2 ---
curl -s http://localhost:8002/v1/distributed/status 2>nul | findstr /i "tasks_processed"
echo.
echo --- NODE 3 ---
curl -s http://localhost:8003/v1/distributed/status 2>nul | findstr /i "tasks_processed"
echo.
echo.
pause
goto MENU

:ELECTION
cls
echo ============================================================
echo              TRIGGERING MANUAL ELECTION
echo ============================================================
echo.
echo Current leader:
curl -s http://localhost:80/v1/distributed/leader 2>nul
echo.
echo.
echo Triggering election...
curl -s -X POST http://localhost:80/v1/distributed/trigger-election 2>nul
echo.
echo.
echo Waiting 5 seconds for election to complete...
timeout /t 5 /nobreak >nul
echo.
echo New leader:
curl -s http://localhost:80/v1/distributed/leader 2>nul
echo.
echo.
pause
goto MENU

:TASKSTATUS
cls
echo ============================================================
echo                  CHECK TASK STATUS
echo ============================================================
echo.
set /p taskid="Enter Task/Request ID: "
echo.
echo Fetching status for: %taskid%
echo.
curl -s http://localhost:80/v1/status/%taskid% 2>nul
echo.
echo.
pause
goto MENU

:HEALTH
cls
echo ============================================================
echo                  NODE HEALTH SUMMARY
echo ============================================================
echo.
echo Fetching health data from all nodes...
echo.
echo ================== NODE 1 ==================
curl -s http://localhost:8001/v1/distributed/status 2>nul
echo.
echo.
echo ================== NODE 2 ==================
curl -s http://localhost:8002/v1/distributed/status 2>nul
echo.
echo.
echo ================== NODE 3 ==================
curl -s http://localhost:8003/v1/distributed/status 2>nul
echo.
echo.
pause
goto MENU

:STRESS
cls
echo ============================================================
echo              STRESS TEST - 10 REQUESTS
echo ============================================================
echo.
echo Sending 10 image analysis requests...
echo.

for /L %%i in (1,1,10) do (
    echo [%%i/10] Sending request...
    curl -s -X POST -F "file=@img/bcp8.jpg" http://localhost:80/v1/analyze 2>nul
    echo.
)

echo.
echo ============================================================
echo All requests sent! Waiting 60 seconds for processing...
timeout /t 60 /nobreak
echo.
echo ============================================================
echo                 FINAL NODE STATISTICS
echo ============================================================
echo.
echo --- NODE 1 ---
curl -s http://localhost:8001/v1/distributed/status 2>nul
echo.
echo.
echo --- NODE 2 ---
curl -s http://localhost:8002/v1/distributed/status 2>nul
echo.
echo.
echo --- NODE 3 ---
curl -s http://localhost:8003/v1/distributed/status 2>nul
echo.
echo.
pause
goto MENU

:KILLLEADER
cls
echo ============================================================
echo              KILLING THE LEADER NODE
echo ============================================================
echo.
echo Step 1: Identifying current leader...
echo.
curl -s http://localhost:8001/v1/distributed/status 2>nul | findstr /i "leader_id"
echo.
echo Checking which node is leader...
for /f "tokens=*" %%a in ('curl -s http://localhost:8001/v1/distributed/status 2^>nul ^| findstr /i "is_leader"') do set leadercheck1=%%a
for /f "tokens=*" %%a in ('curl -s http://localhost:8002/v1/distributed/status 2^>nul ^| findstr /i "is_leader"') do set leadercheck2=%%a
for /f "tokens=*" %%a in ('curl -s http://localhost:8003/v1/distributed/status 2^>nul ^| findstr /i "is_leader"') do set leadercheck3=%%a

echo Node 1: %leadercheck1%
echo Node 2: %leadercheck2%
echo Node 3: %leadercheck3%
echo.

echo Step 2: Stopping the leader (Node 3 - highest ID wins in Bully)...
echo.
docker-compose -f docker-compose.distributed.yml stop node3
echo.
echo ============================================================
echo   LEADER KILLED! Watching election happen...
echo ============================================================
echo.
echo Waiting 10 seconds for failure detection and election...
timeout /t 10 /nobreak >nul
echo.
echo Step 3: Checking new leader...
echo.
echo --- NODE 1 STATUS ---
curl -s http://localhost:8001/v1/distributed/status 2>nul
echo.
echo.
echo --- NODE 2 STATUS ---
curl -s http://localhost:8002/v1/distributed/status 2>nul
echo.
echo.
echo ============================================================
echo   Node 2 should now be the leader (next highest ID)!
echo   Node 3 should show as FAILED in health summary.
echo ============================================================
echo.
pause
goto MENU

:KILLNODE1
cls
echo ============================================================
echo              KILLING NODE 1
echo ============================================================
echo.
echo Current cluster status:
curl -s http://localhost:80/v1/distributed/status 2>nul | findstr /i "alive_nodes"
echo.
echo Stopping Node 1...
docker-compose -f docker-compose.distributed.yml stop node1
echo.
echo Waiting 10 seconds for failure detection...
timeout /t 10 /nobreak >nul
echo.
echo New cluster status:
curl -s http://localhost:8002/v1/distributed/status 2>nul | findstr /i "alive_nodes"
echo.
curl -s http://localhost:8002/v1/distributed/status 2>nul
echo.
pause
goto MENU

:KILLNODE2
cls
echo ============================================================
echo              KILLING NODE 2
echo ============================================================
echo.
echo Current cluster status:
curl -s http://localhost:80/v1/distributed/status 2>nul | findstr /i "alive_nodes"
echo.
echo Stopping Node 2...
docker-compose -f docker-compose.distributed.yml stop node2
echo.
echo Waiting 10 seconds for failure detection...
timeout /t 10 /nobreak >nul
echo.
echo New cluster status (from Node 1 or 3):
curl -s http://localhost:8001/v1/distributed/status 2>nul | findstr /i "alive_nodes"
echo.
curl -s http://localhost:8001/v1/distributed/status 2>nul
echo.
pause
goto MENU

:RESTARTALL
cls
echo ============================================================
echo              RESTARTING ALL NODES
echo ============================================================
echo.
echo Starting all nodes...
docker-compose -f docker-compose.distributed.yml start node1 node2 node3
echo.
echo Waiting 30 seconds for nodes to initialize and elect leader...
timeout /t 30 /nobreak >nul
echo.
echo ============================================================
echo                  CLUSTER RESTORED
echo ============================================================
echo.
echo --- NODE 1 ---
curl -s http://localhost:8001/v1/distributed/status 2>nul
echo.
echo --- NODE 2 ---
curl -s http://localhost:8002/v1/distributed/status 2>nul
echo.
echo --- NODE 3 ---
curl -s http://localhost:8003/v1/distributed/status 2>nul
echo.
pause
goto MENU

:CHAOS
cls
echo ============================================================
echo              CHAOS MODE - ULTIMATE TEST!
echo ============================================================
echo.
echo This test will:
echo   1. Send 3 image requests
echo   2. KILL the leader while processing
echo   3. Send 3 more requests
echo   4. Watch the system recover and continue!
echo.
echo Press any key to start chaos...
pause >nul
echo.
echo ============================================================
echo Step 1: Sending first batch of 3 images...
echo ============================================================
echo.

echo [1/3] Sending...
curl -s -X POST -F "file=@img/bcp8.jpg" http://localhost:80/v1/analyze 2>nul
echo.
echo [2/3] Sending...
curl -s -X POST -F "file=@img/sebks23.jpg" http://localhost:80/v1/analyze 2>nul
echo.
echo [3/3] Sending...
curl -s -X POST -F "file=@img/bcp8.jpg" http://localhost:80/v1/analyze 2>nul
echo.

echo.
echo ============================================================
echo Step 2: KILLING THE LEADER NOW!
echo ============================================================
echo.
docker-compose -f docker-compose.distributed.yml stop node3
echo.
echo Leader killed! Waiting 5 seconds...
timeout /t 5 /nobreak >nul
echo.

echo ============================================================
echo Step 3: Sending second batch (system should recover!)
echo ============================================================
echo.

echo [4/6] Sending to surviving cluster...
curl -s -X POST -F "file=@img/sebks23.jpg" http://localhost:80/v1/analyze 2>nul
echo.
echo [5/6] Sending...
curl -s -X POST -F "file=@img/bcp8.jpg" http://localhost:80/v1/analyze 2>nul
echo.
echo [6/6] Sending...
curl -s -X POST -F "file=@img/sebks23.jpg" http://localhost:80/v1/analyze 2>nul
echo.

echo.
echo ============================================================
echo Step 4: Waiting for processing and checking results...
echo ============================================================
echo.
echo Waiting 30 seconds...
timeout /t 30 /nobreak >nul
echo.

echo --- SURVIVING NODES STATUS ---
echo.
echo Node 1:
curl -s http://localhost:8001/v1/distributed/status 2>nul
echo.
echo.
echo Node 2:
curl -s http://localhost:8002/v1/distributed/status 2>nul
echo.

echo.
echo ============================================================
echo Step 5: Restarting Node 3 to restore cluster...
echo ============================================================
echo.
docker-compose -f docker-compose.distributed.yml start node3
echo.
echo Waiting 60 seconds for Node 3 to fully rejoin the cluster...
echo (Node 3 takes longer to initialize)
timeout /t 60 /nobreak >nul
echo.

echo --- CLUSTER STATUS AFTER NODE 3 REJOIN ---
echo.
echo Node 1:
curl -s http://localhost:8001/v1/distributed/status 2>nul
echo.
echo.
echo Node 2:
curl -s http://localhost:8002/v1/distributed/status 2>nul
echo.
echo.
echo Node 3:
curl -s http://localhost:8003/v1/distributed/status 2>nul
echo.

echo.
echo ============================================================
echo Step 6: Sending third batch to fully restored cluster!
echo ============================================================
echo.

echo [7/9] Sending to restored cluster...
curl -s -X POST -F "file=@img/bcp8.jpg" http://localhost:80/v1/analyze 2>nul
echo.
echo [8/9] Sending...
curl -s -X POST -F "file=@img/sebks23.jpg" http://localhost:80/v1/analyze 2>nul
echo.
echo [9/9] Sending...
curl -s -X POST -F "file=@img/bcp8.jpg" http://localhost:80/v1/analyze 2>nul
echo.

echo.
echo Waiting 30 seconds for final batch to process...
timeout /t 30 /nobreak >nul
echo.

echo --- FINAL CLUSTER STATUS ---
echo.
echo Node 1:
curl -s http://localhost:8001/v1/distributed/status 2>nul
echo.
echo.
echo Node 2:
curl -s http://localhost:8002/v1/distributed/status 2>nul
echo.
echo.
echo Node 3:
curl -s http://localhost:8003/v1/distributed/status 2>nul
echo.

echo.
echo ============================================================
echo   CHAOS TEST COMPLETE!
echo   The system should have:
echo   - Detected leader failure
echo   - Elected a new leader (Node 2)
echo   - Continued processing requests
echo   - Reintegrated Node 3 when it came back
echo   - Processed final batch with all 3 nodes active
echo ============================================================
echo.
pause
goto MENU

:EXIT
cls
echo.
echo Thanks for testing Skin IA Distributed System!
echo.
timeout /t 2 >nul
exit /b 0
