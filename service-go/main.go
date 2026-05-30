package main

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"time"
	"unsafe"
)

const (
	appName       = "Startup Sound Changer"
	serviceName   = "Windows-Shutdown-Sound-Service"
	helperExeName = "Windows-Shutdown-Helper.exe"
	logDirName    = "logs"
	logName       = "service.log"
	pipeName      = `\\.\pipe\WindowsShutdownHelper`

	serviceWin32OwnProcess = 0x00000010
	serviceStopped         = 0x00000001
	serviceStartPending    = 0x00000002
	serviceStopPending     = 0x00000003
	serviceRunning         = 0x00000004

	serviceAcceptStop          = 0x00000001
	serviceAcceptShutdown      = 0x00000004
	serviceAcceptSessionChange = 0x00000080
	serviceAcceptPreshutdown   = 0x00000100

	serviceControlStop          = 0x00000001
	serviceControlShutdown      = 0x00000005
	serviceControlSessionChange = 0x0000000E
	serviceControlPreshutdown   = 0x0000000F

	wtsConsoleConnect = 0x1
	wtsSessionLogon   = 0x5
	wtsSessionUnlock  = 0x8

	genericRead  = 0x80000000
	genericWrite = 0x40000000
	openExisting = 3

	createUnicodeEnvironment = 0x00000400
	invalidSessionID         = 0xFFFFFFFF
	noError                  = 0
)

type serviceStatus struct {
	serviceType             uint32
	currentState            uint32
	controlsAccepted        uint32
	win32ExitCode           uint32
	serviceSpecificExitCode uint32
	checkPoint              uint32
	waitHint                uint32
}

type serviceTableEntry struct {
	serviceName *uint16
	serviceProc uintptr
}

type startupInfo struct {
	cb              uint32
	lpReserved      *uint16
	lpDesktop       *uint16
	lpTitle         *uint16
	dwX             uint32
	dwY             uint32
	dwXSize         uint32
	dwYSize         uint32
	dwXCountChars   uint32
	dwYCountChars   uint32
	dwFillAttribute uint32
	dwFlags         uint32
	wShowWindow     uint16
	cbReserved2     uint16
	lpReserved2     *byte
	hStdInput       syscall.Handle
	hStdOutput      syscall.Handle
	hStdError       syscall.Handle
}

type processInformation struct {
	hProcess    syscall.Handle
	hThread     syscall.Handle
	dwProcessID uint32
	dwThreadID  uint32
}

var (
	advapi32 = syscall.NewLazyDLL("advapi32.dll")
	kernel32 = syscall.NewLazyDLL("kernel32.dll")
	wtsapi32 = syscall.NewLazyDLL("wtsapi32.dll")
	userenv  = syscall.NewLazyDLL("userenv.dll")

	procStartServiceCtrlDispatcherW   = advapi32.NewProc("StartServiceCtrlDispatcherW")
	procRegisterServiceCtrlHandlerExW = advapi32.NewProc("RegisterServiceCtrlHandlerExW")
	procSetServiceStatus              = advapi32.NewProc("SetServiceStatus")
	procCreateProcessAsUserW          = advapi32.NewProc("CreateProcessAsUserW")
	procWTSQueryUserToken             = wtsapi32.NewProc("WTSQueryUserToken")
	procCreateEnvironmentBlock        = userenv.NewProc("CreateEnvironmentBlock")
	procDestroyEnvironmentBlock       = userenv.NewProc("DestroyEnvironmentBlock")
	procWTSGetActiveConsoleSessionId  = kernel32.NewProc("WTSGetActiveConsoleSessionId")
	procWaitNamedPipeW                = kernel32.NewProc("WaitNamedPipeW")
	procCreateFileW                   = kernel32.NewProc("CreateFileW")
	procReadFile                      = kernel32.NewProc("ReadFile")
	procWriteFile                     = kernel32.NewProc("WriteFile")
	procCloseHandle                   = kernel32.NewProc("CloseHandle")
	procWaitForSingleObject           = kernel32.NewProc("WaitForSingleObject")

	serviceHandle syscall.Handle
	stopCh        = make(chan struct{})
)

func programDataDir() string {
	root := os.Getenv("ProgramData")
	if root == "" {
		root = os.Getenv("LOCALAPPDATA")
	}
	if root == "" {
		root = "."
	}
	return filepath.Join(root, appName)
}

func logPath() string { return filepath.Join(programDataDir(), logDirName, logName) }

func writeLog(format string, args ...any) {
	_ = os.MkdirAll(filepath.Dir(logPath()), 0o755)
	f, err := os.OpenFile(logPath(), os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	if err != nil {
		return
	}
	defer f.Close()
	line := fmt.Sprintf(format, args...)
	_, _ = fmt.Fprintf(f, "[%s] pid=%d %s\n", time.Now().Format("2006-01-02 15:04:05"), os.Getpid(), line)
}

func utf16Ptr(s string) *uint16 {
	p, err := syscall.UTF16PtrFromString(s)
	if err != nil {
		return nil
	}
	return p
}

func setStatus(state uint32, waitHint uint32) {
	accepted := uint32(0)
	if state == serviceRunning {
		accepted = serviceAcceptStop | serviceAcceptShutdown | serviceAcceptPreshutdown | serviceAcceptSessionChange
	}
	status := serviceStatus{serviceType: serviceWin32OwnProcess, currentState: state, controlsAccepted: accepted, win32ExitCode: noError, waitHint: waitHint}
	if serviceHandle != 0 {
		procSetServiceStatus.Call(uintptr(serviceHandle), uintptr(unsafe.Pointer(&status)))
	}
}

func serviceMain(argc uint32, argv uintptr) uintptr {
	writeLog("service main starting")
	name := utf16Ptr(serviceName)
	h, _, _ := procRegisterServiceCtrlHandlerExW.Call(uintptr(unsafe.Pointer(name)), syscall.NewCallback(serviceControlHandler), 0)
	if h == 0 {
		writeLog("RegisterServiceCtrlHandlerExW failed")
		return 0
	}
	serviceHandle = syscall.Handle(h)
	setStatus(serviceStartPending, 3000)
	setStatus(serviceRunning, 0)
	writeLog("service running")
	go ensureStandby("service-start")
	<-stopCh
	setStatus(serviceStopped, 0)
	writeLog("service stopped")
	return 0
}

func serviceControlHandler(control uint32, eventType uint32, eventData uintptr, context uintptr) uintptr {
	switch control {
	case serviceControlPreshutdown:
		writeLog("received SERVICE_CONTROL_PRESHUTDOWN")
		setStatus(serviceStopPending, 10000)
		playWithFallback(9000 * time.Millisecond)
		setStatus(serviceRunning, 0)
		writeLog("preshutdown handling finished")
		return noError
	case serviceControlSessionChange:
		writeLog("received SERVICE_CONTROL_SESSIONCHANGE event=%d", eventType)
		if eventType == wtsConsoleConnect || eventType == wtsSessionLogon || eventType == wtsSessionUnlock {
			go ensureStandby(fmt.Sprintf("session-event-%d", eventType))
		}
		return noError
	case serviceControlShutdown:
		writeLog("received SERVICE_CONTROL_SHUTDOWN")
		return noError
	case serviceControlStop:
		writeLog("received SERVICE_CONTROL_STOP")
		setStatus(serviceStopPending, 3000)
		select {
		case <-stopCh:
		default:
			close(stopCh)
		}
		return noError
	default:
		return noError
	}
}

func helperPath() string {
	exe, err := os.Executable()
	if err != nil {
		return helperExeName
	}
	return filepath.Join(filepath.Dir(exe), helperExeName)
}

func ensureStandby(source string) {
	if err := sendCommand("ping", 800*time.Millisecond); err == nil {
		writeLog("standby already reachable source=%s", source)
		return
	}
	writeLog("standby not reachable; launching source=%s", source)
	if err := launchInActiveSession("--standby", false); err != nil {
		writeLog("standby launch failed source=%s err=%v", source, err)
		return
	}
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		if err := sendCommand("ping", 500*time.Millisecond); err == nil {
			writeLog("standby reachable after launch source=%s", source)
			return
		}
		time.Sleep(250 * time.Millisecond)
	}
	writeLog("standby launch did not become reachable source=%s", source)
}

func playWithFallback(timeout time.Duration) {
	done := make(chan error, 1)
	go func() { done <- sendCommand("play", 1500*time.Millisecond) }()
	select {
	case err := <-done:
		if err == nil {
			writeLog("standby playback request completed")
			return
		}
		writeLog("standby playback failed: %v", err)
	case <-time.After(2 * time.Second):
		writeLog("standby playback timed out before fallback")
	}
	writeLog("starting play-now fallback")
	if err := launchInActiveSession("--play-now", true); err != nil {
		writeLog("play-now fallback failed: %v", err)
	}
	select {
	case <-time.After(timeout):
		writeLog("play fallback window elapsed")
	default:
	}
}

func sendCommand(command string, waitTimeout time.Duration) error {
	name := utf16Ptr(pipeName)
	wait, _, err := procWaitNamedPipeW.Call(uintptr(unsafe.Pointer(name)), uintptr(waitTimeout.Milliseconds()))
	if wait == 0 {
		return fmt.Errorf("WaitNamedPipe failed: %v", err)
	}
	h, _, err := procCreateFileW.Call(uintptr(unsafe.Pointer(name)), genericRead|genericWrite, 0, 0, openExisting, 0, 0)
	if h == uintptr(syscall.InvalidHandle) {
		return fmt.Errorf("CreateFile pipe failed: %v", err)
	}
	defer procCloseHandle.Call(h)
	bytes := []byte(command + "\n")
	var written uint32
	ok, _, err := procWriteFile.Call(h, uintptr(unsafe.Pointer(&bytes[0])), uintptr(len(bytes)), uintptr(unsafe.Pointer(&written)), 0)
	if ok == 0 {
		return fmt.Errorf("WriteFile failed: %v", err)
	}
	buf := make([]byte, 128)
	var read uint32
	ok, _, err = procReadFile.Call(h, uintptr(unsafe.Pointer(&buf[0])), uintptr(len(buf)), uintptr(unsafe.Pointer(&read)), 0)
	if ok == 0 {
		return fmt.Errorf("ReadFile failed: %v", err)
	}
	response := string(buf[:read])
	writeLog("helper command=%q response=%q", command, response)
	if command == "ping" && !strings.Contains(response, "pong") {
		return fmt.Errorf("unexpected ping response %q", response)
	}
	return nil
}

func activeSessionID() (uint32, error) {
	r1, _, _ := procWTSGetActiveConsoleSessionId.Call()
	id := uint32(r1)
	if id == invalidSessionID {
		return 0, fmt.Errorf("no active console session")
	}
	return id, nil
}

func launchInActiveSession(arg string, wait bool) error {
	sessionID, err := activeSessionID()
	if err != nil {
		return err
	}
	var token syscall.Handle
	r1, _, err := procWTSQueryUserToken.Call(uintptr(sessionID), uintptr(unsafe.Pointer(&token)))
	if r1 == 0 {
		return fmt.Errorf("WTSQueryUserToken session=%d failed: %v", sessionID, err)
	}
	defer procCloseHandle.Call(uintptr(token))
	var env uintptr
	procCreateEnvironmentBlock.Call(uintptr(unsafe.Pointer(&env)), uintptr(token), 0)
	if env != 0 {
		defer procDestroyEnvironmentBlock.Call(env)
	}
	helper := helperPath()
	cmdLine := fmt.Sprintf("\"%s\" %s", helper, arg)
	cmdPtr := utf16Ptr(cmdLine)
	workDir := utf16Ptr(filepath.Dir(helper))
	desktop := utf16Ptr(`winsta0\default`)
	si := startupInfo{cb: uint32(unsafe.Sizeof(startupInfo{})), lpDesktop: desktop}
	var pi processInformation
	r1, _, err = procCreateProcessAsUserW.Call(
		uintptr(token),
		0,
		uintptr(unsafe.Pointer(cmdPtr)),
		0,
		0,
		0,
		createUnicodeEnvironment,
		env,
		uintptr(unsafe.Pointer(workDir)),
		uintptr(unsafe.Pointer(&si)),
		uintptr(unsafe.Pointer(&pi)),
	)
	if r1 == 0 {
		return fmt.Errorf("CreateProcessAsUser %s session=%d failed: %v", arg, sessionID, err)
	}
	writeLog("launched helper arg=%s session=%d pid=%d", arg, sessionID, pi.dwProcessID)
	if pi.hThread != 0 {
		procCloseHandle.Call(uintptr(pi.hThread))
	}
	if wait && pi.hProcess != 0 {
		procWaitForSingleObject.Call(uintptr(pi.hProcess), 9000)
	}
	if pi.hProcess != 0 {
		procCloseHandle.Call(uintptr(pi.hProcess))
	}
	return nil
}

func runAsConsole() {
	writeLog("console simulation starting")
	ensureStandby("console")
	playWithFallback(9000 * time.Millisecond)
	writeLog("console simulation finished")
}

func main() {
	if len(os.Args) > 1 && os.Args[1] == "--console" {
		runAsConsole()
		return
	}
	writeLog("service process starting args=%v", os.Args[1:])
	entries := []serviceTableEntry{{serviceName: utf16Ptr(serviceName), serviceProc: syscall.NewCallback(serviceMain)}, {}}
	r1, _, err := procStartServiceCtrlDispatcherW.Call(uintptr(unsafe.Pointer(&entries[0])))
	if r1 == 0 {
		writeLog("StartServiceCtrlDispatcherW failed: %v", err)
	}
}
