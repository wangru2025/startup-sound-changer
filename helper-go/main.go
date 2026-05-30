package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"
	"unsafe"
)

const (
	appName        = "Startup Sound Changer"
	settingsName   = "settings.json"
	logDirName     = "logs"
	logName        = "helper.log"
	playMarkerName = "shutdown_play_started.flag"
	mutexName      = "Local\\Windows-Shutdown-Helper"
	pipeName       = `\\.\pipe\WindowsShutdownHelper`
	windowClass    = "WindowsShutdownHelperWindow"
	windowTitle    = "Windows-Shutdown-Helper"

	wmDestroy         = 0x0002
	wmQueryEndSession = 0x0011
	wmEndSession      = 0x0016
	shutdownLevel     = 0x3FF

	sndSync      = 0x0000
	sndMemory    = 0x0004
	sndNoDefault = 0x0002

	errorAlreadyExists = 183
	errorPipeConnected = 535

	pipeAccessDuplex = 0x00000003
	pipeTypeMessage  = 0x00000004
	pipeReadMessage  = 0x00000002
	pipeWait         = 0x00000000
	pipeUnlimited    = 255
)

type point struct{ x, y int32 }

type msg struct {
	hwnd    syscall.Handle
	message uint32
	wParam  uintptr
	lParam  uintptr
	time    uint32
	pt      point
}

type wndClassEx struct {
	cbSize        uint32
	style         uint32
	lpfnWndProc   uintptr
	cbClsExtra    int32
	cbWndExtra    int32
	hInstance     syscall.Handle
	hIcon         syscall.Handle
	hCursor       syscall.Handle
	hbrBackground syscall.Handle
	lpszMenuName  *uint16
	lpszClassName *uint16
	hIconSm       syscall.Handle
}

type settings struct {
	Enabled       bool   `json:"enabled"`
	ShutdownSound string `json:"shutdown_sound"`
}

var (
	kernel32 = syscall.NewLazyDLL("kernel32.dll")
	user32   = syscall.NewLazyDLL("user32.dll")
	winmm    = syscall.NewLazyDLL("winmm.dll")

	procCreateMutexW                 = kernel32.NewProc("CreateMutexW")
	procGetLastError                 = kernel32.NewProc("GetLastError")
	procGetModuleHandleW             = kernel32.NewProc("GetModuleHandleW")
	procSetProcessShutdownParameters = kernel32.NewProc("SetProcessShutdownParameters")
	procCreateNamedPipeW             = kernel32.NewProc("CreateNamedPipeW")
	procConnectNamedPipe             = kernel32.NewProc("ConnectNamedPipe")
	procDisconnectNamedPipe          = kernel32.NewProc("DisconnectNamedPipe")
	procReadFile                     = kernel32.NewProc("ReadFile")
	procWriteFile                    = kernel32.NewProc("WriteFile")
	procCloseHandle                  = kernel32.NewProc("CloseHandle")

	procRegisterClassExW           = user32.NewProc("RegisterClassExW")
	procCreateWindowExW            = user32.NewProc("CreateWindowExW")
	procDefWindowProcW             = user32.NewProc("DefWindowProcW")
	procGetMessageW                = user32.NewProc("GetMessageW")
	procTranslateMessage           = user32.NewProc("TranslateMessage")
	procDispatchMessageW           = user32.NewProc("DispatchMessageW")
	procPostQuitMessage            = user32.NewProc("PostQuitMessage")
	procShutdownBlockReasonCreate  = user32.NewProc("ShutdownBlockReasonCreate")
	procShutdownBlockReasonDestroy = user32.NewProc("ShutdownBlockReasonDestroy")

	procPlaySoundW = winmm.NewProc("PlaySoundW")

	hwnd       syscall.Handle
	played     bool
	blocking   bool
	playMu     sync.Mutex
	soundPath  string
	soundBytes []byte
)

func appDataDir() string {
	root := os.Getenv("LOCALAPPDATA")
	if root == "" {
		root = os.Getenv("USERPROFILE")
	}
	if root == "" {
		root = "."
	}
	return filepath.Join(root, appName)
}

func logPath() string        { return filepath.Join(appDataDir(), logDirName, logName) }
func playMarkerPath() string { return filepath.Join(appDataDir(), playMarkerName) }

func markerAge(window time.Duration) (time.Duration, bool) {
	data, err := os.ReadFile(playMarkerPath())
	if err != nil {
		return 0, false
	}
	unixNano, err := strconv.ParseInt(strings.TrimSpace(string(data)), 10, 64)
	if err != nil {
		return 0, false
	}
	age := time.Since(time.Unix(0, unixNano))
	if age >= 0 && age <= window {
		return age, true
	}
	return age, false
}

func tryClaimPlayback(window time.Duration) bool {
	_ = os.MkdirAll(appDataDir(), 0o755)
	path := playMarkerPath()
	for attempt := 0; attempt < 2; attempt++ {
		file, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o644)
		if err == nil {
			_, _ = file.WriteString(fmt.Sprintf("%d", time.Now().UnixNano()))
			_ = file.Close()
			writeLog("playback marker claimed")
			return true
		}
		if !os.IsExist(err) {
			writeLog("playback marker claim failed: %v", err)
			return false
		}
		if age, recent := markerAge(window); recent {
			writeLog("recent cross-process play marker active: age=%s", age)
			return false
		}
		writeLog("removing stale playback marker")
		_ = os.Remove(path)
	}
	writeLog("playback marker claim lost after stale cleanup")
	return false
}

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

func getLastError() uintptr {
	r1, _, _ := procGetLastError.Call()
	return r1
}

func alreadyRunning() bool {
	name := utf16Ptr(mutexName)
	r1, _, _ := procCreateMutexW.Call(0, 1, uintptr(unsafe.Pointer(name)))
	if r1 == 0 {
		writeLog("CreateMutexW failed last_error=%d", getLastError())
		return false
	}
	last := getLastError()
	writeLog("CreateMutexW last_error=%d", last)
	return last == errorAlreadyExists
}

func setShutdownOrder() {
	r1, _, _ := procSetProcessShutdownParameters.Call(shutdownLevel, 0)
	writeLog("SetProcessShutdownParameters=%t level=%d last_error=%d", r1 != 0, shutdownLevel, getLastError())
}

func loadSound() {
	data, err := os.ReadFile(filepath.Join(appDataDir(), settingsName))
	if err != nil {
		writeLog("settings read failed: %v", err)
		return
	}
	var cfg settings
	if err := json.Unmarshal(data, &cfg); err != nil {
		writeLog("settings parse failed: %v", err)
		return
	}
	if !cfg.Enabled || cfg.ShutdownSound == "" {
		writeLog("settings disabled or empty")
		return
	}
	info, err := os.Stat(cfg.ShutdownSound)
	if err != nil {
		writeLog("sound file missing: %s err=%v", cfg.ShutdownSound, err)
		return
	}
	bytes, err := os.ReadFile(cfg.ShutdownSound)
	if err != nil {
		writeLog("sound preload failed: %v", err)
		return
	}
	soundPath = cfg.ShutdownSound
	soundBytes = bytes
	writeLog("sound loaded: %s file_bytes=%d memory_bytes=%d", soundPath, info.Size(), len(soundBytes))
}

func createShutdownBlockReason(source string) {
	if blocking || hwnd == 0 {
		return
	}
	reason := utf16Ptr("Playing shutdown sound")
	r1, _, _ := procShutdownBlockReasonCreate.Call(uintptr(hwnd), uintptr(unsafe.Pointer(reason)))
	blocking = r1 != 0
	writeLog("ShutdownBlockReasonCreate=%t source=%s last_error=%d", blocking, source, getLastError())
}

func destroyShutdownBlockReason(source string) {
	if !blocking || hwnd == 0 {
		return
	}
	r1, _, _ := procShutdownBlockReasonDestroy.Call(uintptr(hwnd))
	writeLog("ShutdownBlockReasonDestroy=%t source=%s last_error=%d", r1 != 0, source, getLastError())
	blocking = false
}

func playShutdownSound(source string) string {
	playMu.Lock()
	defer playMu.Unlock()
	if played {
		writeLog("%s playback skipped: already played", source)
		return "already-played\n"
	}
	if !tryClaimPlayback(30 * time.Second) {
		played = true
		writeLog("%s playback skipped: playback already claimed", source)
		return "already-played\n"
	}
	if len(soundBytes) == 0 {
		writeLog("%s requested playback with empty cache; reloading", source)
		loadSound()
	}
	if len(soundBytes) == 0 {
		writeLog("%s playback skipped: no sound available", source)
		return "no-sound\n"
	}
	played = true
	writeLog("%s play start: %s", source, soundPath)
	r1, _, _ := procPlaySoundW.Call(uintptr(unsafe.Pointer(&soundBytes[0])), 0, sndMemory|sndSync|sndNoDefault)
	writeLog("%s play finished result=%d", source, r1)
	return "done\n"
}

func createPipe() (syscall.Handle, error) {
	name := utf16Ptr(pipeName)
	r1, _, err := procCreateNamedPipeW.Call(uintptr(unsafe.Pointer(name)), pipeAccessDuplex, pipeTypeMessage|pipeReadMessage|pipeWait, pipeUnlimited, 1024, 1024, 0, 0)
	if r1 == uintptr(syscall.InvalidHandle) {
		return 0, err
	}
	return syscall.Handle(r1), nil
}

func readPipe(handle syscall.Handle) string {
	buf := make([]byte, 128)
	var read uint32
	r1, _, _ := procReadFile.Call(uintptr(handle), uintptr(unsafe.Pointer(&buf[0])), uintptr(len(buf)), uintptr(unsafe.Pointer(&read)), 0)
	if r1 == 0 {
		writeLog("pipe read failed last_error=%d", getLastError())
		return ""
	}
	return strings.TrimSpace(string(buf[:read]))
}

func writePipe(handle syscall.Handle, response string) {
	bytes := []byte(response)
	var written uint32
	r1, _, _ := procWriteFile.Call(uintptr(handle), uintptr(unsafe.Pointer(&bytes[0])), uintptr(len(bytes)), uintptr(unsafe.Pointer(&written)), 0)
	if r1 == 0 {
		writeLog("pipe write failed last_error=%d", getLastError())
		return
	}
	writeLog("pipe response written: %q bytes=%d", strings.TrimSpace(response), written)
}

func servePipe() {
	writeLog("pipe server entering: %s", pipeName)
	for {
		pipe, err := createPipe()
		if err != nil {
			writeLog("CreateNamedPipe failed: %v last_error=%d", err, getLastError())
			time.Sleep(time.Second)
			continue
		}
		r1, _, _ := procConnectNamedPipe.Call(uintptr(pipe), 0)
		if r1 == 0 && getLastError() != errorPipeConnected {
			writeLog("ConnectNamedPipe failed last_error=%d", getLastError())
			procCloseHandle.Call(uintptr(pipe))
			continue
		}
		command := readPipe(pipe)
		writeLog("pipe command: %q", command)
		response := "unknown\n"
		switch strings.ToLower(command) {
		case "play":
			loadSound()
			response = playShutdownSound("SERVICE")
		case "ping":
			response = "pong\n"
		}
		writePipe(pipe, response)
		procDisconnectNamedPipe.Call(uintptr(pipe))
		procCloseHandle.Call(uintptr(pipe))
	}
}

func wndProc(h syscall.Handle, message uint32, wParam uintptr, lParam uintptr) uintptr {
	switch message {
	case wmQueryEndSession:
		writeLog("received WM_QUERYENDSESSION: hwnd=%d wparam=%d lparam=%d played=%t", h, wParam, lParam, played)
		createShutdownBlockReason("WM_QUERYENDSESSION")
		loadSound()
		playShutdownSound("WM_QUERYENDSESSION")
		destroyShutdownBlockReason("WM_QUERYENDSESSION")
		return 1
	case wmEndSession:
		writeLog("received WM_ENDSESSION: hwnd=%d wparam=%d lparam=%d played=%t", h, wParam, lParam, played)
		return 0
	case wmDestroy:
		writeLog("received WM_DESTROY")
		procPostQuitMessage.Call(0)
		return 0
	default:
		r1, _, _ := procDefWindowProcW.Call(uintptr(h), uintptr(message), wParam, lParam)
		return r1
	}
}

func createHiddenWindow() (syscall.Handle, error) {
	hInstanceRaw, _, _ := procGetModuleHandleW.Call(0)
	hInstance := syscall.Handle(hInstanceRaw)
	className := utf16Ptr(windowClass)
	wc := wndClassEx{cbSize: uint32(unsafe.Sizeof(wndClassEx{})), lpfnWndProc: syscall.NewCallback(wndProc), hInstance: hInstance, lpszClassName: className}
	r1, _, _ := procRegisterClassExW.Call(uintptr(unsafe.Pointer(&wc)))
	if r1 == 0 {
		return 0, fmt.Errorf("RegisterClassExW failed last_error=%d", getLastError())
	}
	title := utf16Ptr(windowTitle)
	hwndRaw, _, _ := procCreateWindowExW.Call(0, uintptr(unsafe.Pointer(className)), uintptr(unsafe.Pointer(title)), 0, 0, 0, 0, 0, 0, 0, uintptr(hInstance), 0)
	if hwndRaw == 0 {
		return 0, fmt.Errorf("CreateWindowExW failed last_error=%d", getLastError())
	}
	return syscall.Handle(hwndRaw), nil
}

func messageLoop() int {
	var m msg
	writeLog("message loop entering")
	for {
		r1, _, _ := procGetMessageW.Call(uintptr(unsafe.Pointer(&m)), 0, 0, 0)
		if int32(r1) == 0 {
			writeLog("message loop quit: code=%d", m.wParam)
			return int(m.wParam)
		}
		if int32(r1) == -1 {
			writeLog("GetMessageW failed last_error=%d", getLastError())
			return 1
		}
		procTranslateMessage.Call(uintptr(unsafe.Pointer(&m)))
		procDispatchMessageW.Call(uintptr(unsafe.Pointer(&m)))
	}
}

func runStandby() {
	if alreadyRunning() {
		writeLog("exiting: already running")
		return
	}
	setShutdownOrder()
	loadSound()
	go servePipe()
	created, err := createHiddenWindow()
	if err != nil {
		writeLog("fatal: %v", err)
		os.Exit(1)
	}
	hwnd = created
	writeLog("hidden window created: hwnd=%d", hwnd)
	os.Exit(messageLoop())
}

func main() {
	writeLog("go helper starting args=%v", os.Args[1:])
	if len(os.Args) > 1 && os.Args[1] == "--play-now" {
		loadSound()
		playShutdownSound("PLAY_NOW")
		return
	}
	runStandby()
}
