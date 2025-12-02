@echo off
REM Quick gRPC Distributed System Test

echo ================================================================================
echo SKIN IA - gRPC DISTRIBUTED SYSTEM TEST
echo ================================================================================
echo.

echo [TEST 1] Health Check
echo ================================================================================
curl -s http://localhost:8001/healthz
echo.
curl -s http://localhost:8002/healthz
echo.
curl -s http://localhost:8003/healthz
echo.
timeout /t 2 /nobreak >nul

echo [TEST 2] System Status - Verify gRPC is Active
echo ================================================================================
echo Node 1:
curl -s http://localhost:8001/v1/distributed/status | python -m json.tool
echo.
timeout /t 1 /nobreak >nul

echo Node 2:
curl -s http://localhost:8002/v1/distributed/status | python -m json.tool
echo.
timeout /t 1 /nobreak >nul

echo Node 3:
curl -s http://localhost:8003/v1/distributed/status | python -m json.tool
echo.
timeout /t 2 /nobreak >nul

echo [TEST 3] Leader Election (Should be Node 3)
echo ================================================================================
curl -s http://localhost:8001/v1/distributed/leader | python -m json.tool
echo.
curl -s http://localhost:8002/v1/distributed/leader | python -m json.tool
echo.
curl -s http://localhost:8003/v1/distributed/leader | python -m json.tool
echo.
timeout /t 2 /nobreak >nul

echo [TEST 4] Lamport Clocks
echo ================================================================================
for /L %%i in (1,1,3) do (
    echo Node %%i:
    curl -s http://localhost:800%%i/v1/distributed/status | python -c "import sys, json; d=json.load(sys.stdin); print(f'  Clock: {d[\"lamport_clock\"]}')"
)
echo.
timeout /t 2 /nobreak >nul

echo [TEST 5] Image Analysis via gRPC Distribution
echo ================================================================================
echo.
echo Submitting test images from img folder...
echo.

for %%f in (img\*.jpg img\*.png) do (
    echo Processing: %%f
    curl -s -X POST http://localhost/v1/analyze-pytorch -F "file=@%%f" | python -c "import sys, json; d=json.load(sys.stdin); print(f'  Request: {d.get(\"request_id\")}, Assigned to Node: {d.get(\"assigned_to_node\", \"local\")}, Distributed: {d.get(\"distributed\", False)}, Framework: {d.get(\"framework\", \"N/A\")}')"
    echo.
    timeout /t 1 /nobreak >nul
)

echo.
timeout /t 2 /nobreak >nul

echo [TEST 6] Trigger Manual Election
echo ================================================================================
echo Triggering election...
curl -s -X POST http://localhost:8001/v1/distributed/trigger-election | python -m json.tool
echo.
echo Waiting for election to complete...
timeout /t 8 /nobreak >nul
echo.
echo New leader:
curl -s http://localhost:8001/v1/distributed/leader | python -m json.tool
echo.
timeout /t 2 /nobreak >nul

echo [TEST 7] Heartbeat Status
echo ================================================================================
for /L %%i in (1,1,3) do (
    echo Node %%i heartbeat:
    curl -s http://localhost:800%%i/v1/distributed/status | python -c "import sys, json; d=json.load(sys.stdin); print(json.dumps(d.get('health_summary', {}), indent=2))" 2>nul
    echo.
)
timeout /t 2 /nobreak >nul

echo [TEST 8] Multiple Requests - Task Distribution
echo ================================================================================
echo Submitting multiple requests to test load balancing...
echo.

set count=0
for %%f in (img\*.jpg img\*.png) do (
    set /a count+=1
    if !count! LEQ 5 (
        echo Request !count!:
        curl -s -X POST http://localhost/v1/analyze-pytorch -F "file=@%%f" | python -c "import sys, json; d=json.load(sys.stdin); print(f'  Assigned to Node: {d.get(\"assigned_to_node\", \"N/A\")}')"
        echo.
        timeout /t 1 /nobreak >nul
    )
)
echo.

echo [TEST 9] Final Status
echo ================================================================================
for /L %%i in (1,1,3) do (
    echo === NODE %%i ===
    curl -s http://localhost:800%%i/v1/distributed/status | python -c "import sys, json; d=json.load(sys.stdin); print(f'  Leader: {d[\"is_leader\"]}, Leader ID: {d[\"leader_id\"]}, Clock: {d[\"lamport_clock\"]}, Alive: {d[\"alive_nodes\"]}, Tasks: {d.get(\"tasks_processed\", 0)}')" 2>nul
    echo.
)

echo ================================================================================
echo TESTS COMPLETE
echo ================================================================================
echo.
echo Verify gRPC in logs:
echo   docker logs tpfinal-node1-1 ^| findstr "gRPC"
echo   docker logs tpfinal-node2-1 ^| findstr "gRPC"
echo   docker logs tpfinal-node3-1 ^| findstr "gRPC"
echo.
pause
