# 47 · 导入表（基础设施地图）

> 工具：`tools/iat.py`（本文件 `TimeDateStamp==0`，故沿 OriginalFirstThunk 走到空项计长）。
> 共 **306 个导入 / 14 个 DLL**，地址为原生 VA。

## 1. 总览

| DLL | 数量 | 用途 |
|---|---|---|
| `KERNEL32.dll` | 134 | 系统调用（文件/线程/内存/时间） |
| `USER32.dll` | 41 | 窗口/消息/光标 |
| `d3dx9_30.dll` | 39 | ★ D3DX9 数学与资源辅助（**大量函数为 inline，会被内联进调用者**） |
| `fmodex.dll` | 36 | ★ FMOD Ex 音频引擎（36 个） |
| `WS2_32.dll` | 24 | Winsock 网络（LAN 对战） |
| `fmod_event.dll` | 10 | FMOD 事件系统 |
| `ole32.dll` | 6 | COM |
| `OLEAUT32.dll` | 6 | COM 自动化 |
| `ADVAPI32.dll` | 5 | 注册表/安全 |
| `d3d9.dll` | 1 | ★ 仅 Direct3DCreate9（其余走 COM 虚表） |
| `DINPUT8.dll` | 1 | 仅 DirectInput8Create |
| `WINMM.dll` | 1 | 仅 timeGetTime |
| `GDI32.dll` | 1 | 仅 GetStockObject |
| `dbghelp.dll` | 1 | 仅 MiniDumpWriteDump（崩溃转储） |

## 2. ★★★ 对逆向结论的直接影响

1. **`D3DXVec3Transform` / `D3DXVec4Transform` / `D3DXMatrixMultiply` / `D3DXMatrixInverse` / `D3DXMatrixTranspose` / `D3DXVec3Normalize` / `D3DXPlaneTransform` 均被导入**，
   而它们在 `d3dx9math.inl` 中是 **inline** 函数 ⇒ **编译器会把它们内联进调用者**。
   **⇒ 项目里多处被识别为「M·v+t 仿射变换形状」的函数（如 `0x6BB550`、`0x6A0460` 的批量变换）应优先判定为内联的 D3DX 数学**，
   而非游戏特有算法 —— 只有 D3DX 未提供的算法才需逐条还原。
2. **`D3DXAssembleShader` + `D3DXGetShaderConstantTable` + `D3DXGatherFragments*`** ⇒ 着色器以 **shader 汇编文本**形式提供或运行时汇编；
   渲染线若找不到编译好的字节码，应在文本/数据文件里找 `.vsh/.psh`。
3. **只有 `Direct3DCreate9` 一个 d3d9 导入** ⇒ 所有 D3D 调用都是 COM 虚表调用（偏移即接口方法号）。
4. **FMOD Ex（`fmodex.dll` 36 + `fmod_event.dll` 10）** ⇒ 音频线重制替换调用即可。
5. **`d3dx9_30.dll` 是运行时依赖**（DirectX 9.0c 2007 年 8 月版）。
6. `dbghelp!MiniDumpWriteDump` ⇒ 自带崩溃转储（调试线索）。
7. **时间源有两个**：`WINMM!timeGetTime` 与 `KERNEL32!QueryPerformanceCounter/Frequency` ⇒ 反推 dt 时需对照（`docs/44` §14）。

## 3. 完整表

### KERNEL32.dll（134）

| IAT VA | 函数 |
|---|---|
| `0x006e7028` | `GetUserDefaultLCID` |
| `0x006e702c` | `GetStringTypeW` |
| `0x006e7030` | `GetStringTypeA` |
| `0x006e7034` | `SetStdHandle` |
| `0x006e7038` | `GetCPInfo` |
| `0x006e703c` | `GetOEMCP` |
| `0x006e7040` | `GetACP` |
| `0x006e7044` | `IsBadCodePtr` |
| `0x006e7048` | `IsBadReadPtr` |
| `0x006e704c` | `VirtualProtect` |
| `0x006e7050` | `LCMapStringW` |
| `0x006e7054` | `LCMapStringA` |
| `0x006e7058` | `GetFileAttributesA` |
| `0x006e705c` | `GetEnvironmentStringsW` |
| `0x006e7060` | `FreeEnvironmentStringsW` |
| `0x006e7064` | `GetEnvironmentStrings` |
| `0x006e7068` | `FreeEnvironmentStringsA` |
| `0x006e706c` | `UnhandledExceptionFilter` |
| `0x006e7070` | `GetModuleFileNameA` |
| `0x006e7074` | `GetTimeZoneInformation` |
| `0x006e7078` | `GetLocaleInfoA` |
| `0x006e707c` | `GetStdHandle` |
| `0x006e7080` | `SetHandleCount` |
| `0x006e7084` | `VirtualQuery` |
| `0x006e7088` | `SetUnhandledExceptionFilter` |
| `0x006e708c` | `HeapSize` |
| `0x006e7090` | `TlsGetValue` |
| `0x006e7094` | `TlsSetValue` |
| `0x006e7098` | `TlsFree` |
| `0x006e709c` | `SetLastError` |
| `0x006e70a0` | `TlsAlloc` |
| `0x006e70a4` | `IsBadWritePtr` |
| `0x006e70a8` | `VirtualAlloc` |
| `0x006e70ac` | `VirtualFree` |
| `0x006e70b0` | `HeapCreate` |
| `0x006e70b4` | `HeapDestroy` |
| `0x006e70b8` | `GetStartupInfoA` |
| `0x006e70bc` | `ExitProcess` |
| `0x006e70c0` | `EnumSystemLocalesA` |
| `0x006e70c4` | `IsValidLocale` |
| `0x006e70c8` | `GetSystemTimeAsFileTime` |
| `0x006e70cc` | `HeapReAlloc` |
| `0x006e70d0` | `RtlUnwind` |
| `0x006e70d4` | `IsValidCodePage` |
| `0x006e70d8` | `SetEndOfFile` |
| `0x006e70dc` | `CompareStringW` |
| `0x006e70e0` | `SetEnvironmentVariableA` |
| `0x006e70e4` | `GetExitCodeProcess` |
| `0x006e70e8` | `GetFileType` |
| `0x006e70ec` | `CreateFileA` |
| `0x006e70f0` | `GlobalAlloc` |
| `0x006e70f4` | `GlobalFree` |
| `0x006e70f8` | `WideCharToMultiByte` |
| `0x006e70fc` | `OutputDebugStringW` |
| `0x006e7100` | `GetVersionExW` |
| `0x006e7104` | `IsDBCSLeadByteEx` |
| `0x006e7108` | `MultiByteToWideChar` |
| `0x006e710c` | `lstrlenW` |
| `0x006e7110` | `lstrcpyW` |
| `0x006e7114` | `GetLocaleInfoW` |
| `0x006e7118` | `CompareStringA` |
| `0x006e711c` | `GetProcessHeap` |
| `0x006e7120` | `HeapAlloc` |
| `0x006e7124` | `HeapFree` |
| `0x006e7128` | `lstrcatW` |
| `0x006e712c` | `FreeLibrary` |
| `0x006e7130` | `LoadLibraryA` |
| `0x006e7134` | `GetProcAddress` |
| `0x006e7138` | `CreateEventA` |
| `0x006e713c` | `FindClose` |
| `0x006e7140` | `FindNextFileA` |
| `0x006e7144` | `FindFirstFileA` |
| `0x006e7148` | `FlushFileBuffers` |
| `0x006e714c` | `DeleteFileA` |
| `0x006e7150` | `RemoveDirectoryA` |
| `0x006e7154` | `DosDateTimeToFileTime` |
| `0x006e7158` | `SetFileTime` |
| `0x006e715c` | `GetFileTime` |
| `0x006e7160` | `FileTimeToDosDateTime` |
| `0x006e7164` | `MoveFileA` |
| `0x006e7168` | `CopyFileA` |
| `0x006e716c` | `CreateDirectoryA` |
| `0x006e7170` | `FormatMessageA` |
| `0x006e7174` | `OpenEventA` |
| `0x006e7178` | `CreateFileMappingA` |
| `0x006e717c` | `MapViewOfFile` |
| `0x006e7180` | `SetEvent` |
| `0x006e7184` | `UnmapViewOfFile` |
| `0x006e7188` | `SetFilePointer` |
| `0x006e718c` | `GetLocalTime` |
| `0x006e7190` | `WriteFile` |
| `0x006e7194` | `GetVersionExA` |
| `0x006e7198` | `GetSystemInfo` |
| `0x006e719c` | `GlobalMemoryStatus` |
| `0x006e71a0` | `GetCurrentThreadId` |
| `0x006e71a4` | `GetCurrentProcessId` |
| `0x006e71a8` | `CreateProcessA` |
| `0x006e71ac` | `GetFileSize` |
| `0x006e71b0` | `ReadFile` |
| `0x006e71b4` | `CreateMutexA` |
| `0x006e71b8` | `ReleaseMutex` |
| `0x006e71bc` | `GetCurrentProcess` |
| `0x006e71c0` | `SetPriorityClass` |
| `0x006e71c4` | `GetModuleHandleA` |
| `0x006e71c8` | `GetSystemDirectoryW` |
| `0x006e71cc` | `LoadLibraryW` |
| `0x006e71d0` | `OutputDebugStringA` |
| `0x006e71d4` | `GlobalMemoryStatusEx` |
| `0x006e71d8` | `GetCommandLineA` |
| `0x006e71dc` | `QueryPerformanceFrequency` |
| `0x006e71e0` | `QueryPerformanceCounter` |
| `0x006e71e4` | `GetLastError` |
| `0x006e71e8` | `WaitForSingleObject` |
| `0x006e71ec` | `CreateSemaphoreA` |
| `0x006e71f0` | `InterlockedIncrement` |
| `0x006e71f4` | `CloseHandle` |
| `0x006e71f8` | `CreateThread` |
| `0x006e71fc` | `ExitThread` |
| `0x006e7200` | `ResumeThread` |
| `0x006e7204` | `GetCurrentDirectoryA` |
| `0x006e7208` | `TerminateProcess` |
| `0x006e720c` | `GetTickCount` |
| `0x006e7210` | `InterlockedExchange` |
| `0x006e7214` | `ReleaseSemaphore` |
| `0x006e7218` | `InitializeCriticalSection` |
| `0x006e721c` | `DeleteCriticalSection` |
| `0x006e7220` | `EnterCriticalSection` |
| `0x006e7224` | `LeaveCriticalSection` |
| `0x006e7228` | `PostQueuedCompletionStatus` |
| `0x006e722c` | `InterlockedDecrement` |
| `0x006e7230` | `InterlockedExchangeAdd` |
| `0x006e7234` | `Sleep` |
| `0x006e7238` | `SetThreadPriority` |
| `0x006e723c` | `RaiseException` |

### USER32.dll（41）

| IAT VA | 函数 |
|---|---|
| `0x006e7260` | `PostQuitMessage` |
| `0x006e7264` | `PeekMessageA` |
| `0x006e7268` | `ShowCursor` |
| `0x006e726c` | `GetCursorPos` |
| `0x006e7270` | `ClipCursor` |
| `0x006e7274` | `SetCursor` |
| `0x006e7278` | `GetForegroundWindow` |
| `0x006e727c` | `SetForegroundWindow` |
| `0x006e7280` | `DefWindowProcA` |
| `0x006e7284` | `SetWindowLongA` |
| `0x006e7288` | `RegisterClassExA` |
| `0x006e728c` | `UpdateWindow` |
| `0x006e7290` | `PostMessageA` |
| `0x006e7294` | `GetKeyboardLayoutList` |
| `0x006e7298` | `GetFocus` |
| `0x006e729c` | `PostMessageW` |
| `0x006e72a0` | `GetAsyncKeyState` |
| `0x006e72a4` | `GetKeyState` |
| `0x006e72a8` | `SendMessageW` |
| `0x006e72ac` | `keybd_event` |
| `0x006e72b0` | `wsprintfA` |
| `0x006e72b4` | `GetKeyboardLayout` |
| `0x006e72b8` | `ToUnicodeEx` |
| `0x006e72bc` | `GetKeyboardState` |
| `0x006e72c0` | `MapVirtualKeyExA` |
| `0x006e72c4` | `ToAsciiEx` |
| `0x006e72c8` | `SetFocus` |
| `0x006e72cc` | `TranslateMessage` |
| `0x006e72d0` | `DispatchMessageA` |
| `0x006e72d4` | `SetWindowPos` |
| `0x006e72d8` | `GetWindowLongA` |
| `0x006e72dc` | `DestroyWindow` |
| `0x006e72e0` | `MessageBoxA` |
| `0x006e72e4` | `LoadIconA` |
| `0x006e72e8` | `LoadCursorA` |
| `0x006e72ec` | `RegisterClassA` |
| `0x006e72f0` | `CreateWindowExA` |
| `0x006e72f4` | `GetDesktopWindow` |
| `0x006e72f8` | `MoveWindow` |
| `0x006e72fc` | `ShowWindow` |
| `0x006e7300` | `GetClientRect` |

### d3dx9_30.dll（39）

| IAT VA | 函数 |
|---|---|
| `0x006e737c` | `D3DXCreateFragmentLinker` |
| `0x006e7380` | `D3DXMatrixMultiply` |
| `0x006e7384` | `D3DXMatrixPerspectiveFovRH` |
| `0x006e7388` | `D3DXMatrixOrthoOffCenterRH` |
| `0x006e738c` | `D3DXMatrixPerspectiveOffCenterRH` |
| `0x006e7390` | `D3DXMatrixInverse` |
| `0x006e7394` | `D3DXSHRotate` |
| `0x006e7398` | `D3DXSHEvalHemisphereLight` |
| `0x006e739c` | `D3DXFillTexture` |
| `0x006e73a0` | `D3DXLoadSurfaceFromSurface` |
| `0x006e73a4` | `D3DXVec3Normalize` |
| `0x006e73a8` | `D3DXVec4Normalize` |
| `0x006e73ac` | `D3DXVec4Transform` |
| `0x006e73b0` | `D3DXMatrixTranspose` |
| `0x006e73b4` | `D3DXPlaneNormalize` |
| `0x006e73b8` | `D3DXPlaneTransform` |
| `0x006e73bc` | `D3DXMatrixLookAtLH` |
| `0x006e73c0` | `D3DXCreateTextureFromFileA` |
| `0x006e73c4` | `D3DXSaveTextureToFileA` |
| `0x006e73c8` | `D3DXCreateTexture` |
| `0x006e73cc` | `D3DXCreateTeapot` |
| `0x006e73d0` | `D3DXCreateSphere` |
| `0x006e73d4` | `D3DXCreateTorus` |
| `0x006e73d8` | `D3DXMatrixPerspectiveFovLH` |
| `0x006e73dc` | `D3DXCreateMeshFVF` |
| `0x006e73e0` | `D3DXAssembleShader` |
| `0x006e73e4` | `D3DXAssembleShaderFromFileA` |
| `0x006e73e8` | `D3DXGatherFragmentsFromFileA` |
| `0x006e73ec` | `D3DXGatherFragments` |
| `0x006e73f0` | `D3DXGetShaderConstantTable` |
| `0x006e73f4` | `D3DXCreateBuffer` |
| `0x006e73f8` | `D3DXVec3Transform` |
| `0x006e73fc` | `D3DXMatrixRotationZ` |
| `0x006e7400` | `D3DXMatrixLookAtRH` |
| `0x006e7404` | `D3DXFilterTexture` |
| `0x006e7408` | `D3DXLoadSurfaceFromMemory` |
| `0x006e740c` | `D3DXFillCubeTexture` |
| `0x006e7410` | `D3DXCreateTextureFromFileInMemoryEx` |
| `0x006e7414` | `D3DXCreateTextureFromFileExA` |

### fmodex.dll（36）

| IAT VA | 函数 |
|---|---|
| `0x006e7450` | `?getLength@Sound@FMOD@@QAG?AW4FMOD_RESULT@@PAII@Z` |
| `0x006e7454` | `?playSound@System@FMOD@@QAG?AW4FMOD_RESULT@@W4FMOD_CHANNELINDEX@@PAVSound@2@_NPAPAVChannel@2@@Z` |
| `0x006e7458` | `?stop@Channel@FMOD@@QAG?AW4FMOD_RESULT@@XZ` |
| `0x006e745c` | `?getUserData@Sound@FMOD@@QAG?AW4FMOD_RESULT@@PAPAX@Z` |
| `0x006e7460` | `?createSound@System@FMOD@@QAG?AW4FMOD_RESULT@@PBDIPAUFMOD_CREATESOUNDEXINFO@@PAPAVSound@2@@Z` |
| `0x006e7464` | `?release@Sound@FMOD@@QAG?AW4FMOD_RESULT@@XZ` |
| `0x006e7468` | `FMOD_Memory_Initialize` |
| `0x006e746c` | `?getDriverCaps@System@FMOD@@QAG?AW4FMOD_RESULT@@HPAIPAH1PAW4FMOD_SPEAKERMODE@@@Z` |
| `0x006e7470` | `?getHardwareChannels@System@FMOD@@QAG?AW4FMOD_RESULT@@PAH00@Z` |
| `0x006e7474` | `?isPlaying@Channel@FMOD@@QAG?AW4FMOD_RESULT@@PA_N@Z` |
| `0x006e7478` | `?getCPUUsage@System@FMOD@@QAG?AW4FMOD_RESULT@@PAM000@Z` |
| `0x006e747c` | `?release@DSP@FMOD@@QAG?AW4FMOD_RESULT@@XZ` |
| `0x006e7480` | `?getChannelsPlaying@System@FMOD@@QAG?AW4FMOD_RESULT@@PAH@Z` |
| `0x006e7484` | `?set3DListenerAttributes@System@FMOD@@QAG?AW4FMOD_RESULT@@HPBUFMOD_VECTOR@@000@Z` |
| `0x006e7488` | `?setBypass@DSP@FMOD@@QAG?AW4FMOD_RESULT@@_N@Z` |
| `0x006e748c` | `?setReverbProperties@System@FMOD@@QAG?AW4FMOD_RESULT@@PBUFMOD_REVERB_PROPERTIES@@@Z` |
| `0x006e7490` | `?release@Geometry@FMOD@@QAG?AW4FMOD_RESULT@@XZ` |
| `0x006e7494` | `?loadGeometry@System@FMOD@@QAG?AW4FMOD_RESULT@@PBXHPAPAVGeometry@2@@Z` |
| `0x006e7498` | `?getOpenState@Sound@FMOD@@QAG?AW4FMOD_RESULT@@PAW4FMOD_OPENSTATE@@PAIPA_N@Z` |
| `0x006e749c` | `?setPaused@Channel@FMOD@@QAG?AW4FMOD_RESULT@@_N@Z` |
| `0x006e74a0` | `?set3DMinMaxDistance@Sound@FMOD@@QAG?AW4FMOD_RESULT@@MM@Z` |
| `0x006e74a4` | `?setHardwareChannels@System@FMOD@@QAG?AW4FMOD_RESULT@@HHHH@Z` |
| `0x006e74a8` | `?setSoftwareChannels@System@FMOD@@QAG?AW4FMOD_RESULT@@H@Z` |
| `0x006e74ac` | `?setPluginPath@System@FMOD@@QAG?AW4FMOD_RESULT@@PBD@Z` |
| `0x006e74b0` | `?setSpeakerMode@System@FMOD@@QAG?AW4FMOD_RESULT@@W4FMOD_SPEAKERMODE@@@Z` |
| `0x006e74b4` | `?getOutput@System@FMOD@@QAG?AW4FMOD_RESULT@@PAW4FMOD_OUTPUTTYPE@@@Z` |
| `0x006e74b8` | `?getMode@Channel@FMOD@@QAG?AW4FMOD_RESULT@@PAI@Z` |
| `0x006e74bc` | `?setPan@Channel@FMOD@@QAG?AW4FMOD_RESULT@@M@Z` |
| `0x006e74c0` | `?set3DAttributes@Channel@FMOD@@QAG?AW4FMOD_RESULT@@PBUFMOD_VECTOR@@0@Z` |
| `0x006e74c4` | `?set3DConeOrientation@Channel@FMOD@@QAG?AW4FMOD_RESULT@@PAUFMOD_VECTOR@@@Z` |
| `0x006e74c8` | `?setVolume@Channel@FMOD@@QAG?AW4FMOD_RESULT@@M@Z` |
| `0x006e74cc` | `?getDefaults@Sound@FMOD@@QAG?AW4FMOD_RESULT@@PAM00PAH@Z` |
| `0x006e74d0` | `?setFrequency@Channel@FMOD@@QAG?AW4FMOD_RESULT@@M@Z` |
| `0x006e74d4` | `?setPriority@Channel@FMOD@@QAG?AW4FMOD_RESULT@@H@Z` |
| `0x006e74d8` | `?isVirtual@Channel@FMOD@@QAG?AW4FMOD_RESULT@@PA_N@Z` |
| `0x006e74dc` | `FMOD_Memory_GetStats` |

### WS2_32.dll（24）

| IAT VA | 函数 |
|---|---|
| `0x006e7310` | `ord#19` |
| `0x006e7314` | `ord#4` |
| `0x006e7318` | `ord#16` |
| `0x006e731c` | `ord#22` |
| `0x006e7320` | `ord#20` |
| `0x006e7324` | `ord#7` |
| `0x006e7328` | `WSASocketA` |
| `0x006e732c` | `WSAIoctl` |
| `0x006e7330` | `ord#17` |
| `0x006e7334` | `ord#14` |
| `0x006e7338` | `ord#2` |
| `0x006e733c` | `ord#12` |
| `0x006e7340` | `ord#23` |
| `0x006e7344` | `ord#21` |
| `0x006e7348` | `ord#8` |
| `0x006e734c` | `ord#3` |
| `0x006e7350` | `ord#6` |
| `0x006e7354` | `ord#116` |
| `0x006e7358` | `ord#115` |
| `0x006e735c` | `ord#52` |
| `0x006e7360` | `ord#57` |
| `0x006e7364` | `ord#111` |
| `0x006e7368` | `ord#9` |
| `0x006e736c` | `ord#15` |

### fmod_event.dll（10）

| IAT VA | 函数 |
|---|---|
| `0x006e7424` | `?getParameterByIndex@Event@FMOD@@QAG?AW4FMOD_RESULT@@HPAPAVEventParameter@2@@Z` |
| `0x006e7428` | `?start@Event@FMOD@@QAG?AW4FMOD_RESULT@@XZ` |
| `0x006e742c` | `?setValue@EventParameter@FMOD@@QAG?AW4FMOD_RESULT@@M@Z` |
| `0x006e7430` | `?getInfo@Event@FMOD@@QAG?AW4FMOD_RESULT@@PAHPAPADPAPAPAD@Z` |
| `0x006e7434` | `?getRange@EventParameter@FMOD@@QAG?AW4FMOD_RESULT@@PAM0@Z` |
| `0x006e7438` | `?setVolume@Event@FMOD@@QAG?AW4FMOD_RESULT@@M@Z` |
| `0x006e743c` | `?set3DAttributes@Event@FMOD@@QAG?AW4FMOD_RESULT@@PBUFMOD_VECTOR@@00@Z` |
| `0x006e7440` | `?EventSystem_Create@FMOD@@YG?AW4FMOD_RESULT@@PAPAVEventSystem@1@@Z` |
| `0x006e7444` | `?getState@Event@FMOD@@QAG?AW4FMOD_RESULT@@PAI@Z` |
| `0x006e7448` | `?stop@Event@FMOD@@QAG?AW4FMOD_RESULT@@XZ` |

### ole32.dll（6）

| IAT VA | 函数 |
|---|---|
| `0x006e74e4` | `CoUninitialize` |
| `0x006e74e8` | `OleUninitialize` |
| `0x006e74ec` | `OleSetContainedObject` |
| `0x006e74f0` | `OleCreate` |
| `0x006e74f4` | `OleInitialize` |
| `0x006e74f8` | `CoInitialize` |

### OLEAUT32.dll（6）

| IAT VA | 函数 |
|---|---|
| `0x006e7244` | `ord#15` |
| `0x006e7248` | `ord#2` |
| `0x006e724c` | `ord#8` |
| `0x006e7250` | `ord#16` |
| `0x006e7254` | `ord#23` |
| `0x006e7258` | `ord#9` |

### ADVAPI32.dll（5）

| IAT VA | 函数 |
|---|---|
| `0x006e7000` | `RegCloseKey` |
| `0x006e7004` | `RegQueryValueExA` |
| `0x006e7008` | `RegOpenKeyExA` |
| `0x006e700c` | `RegOpenKeyExW` |
| `0x006e7010` | `RegQueryValueExW` |

### d3d9.dll（1）

| IAT VA | 函数 |
|---|---|
| `0x006e7374` | `Direct3DCreate9` |

### DINPUT8.dll（1）

| IAT VA | 函数 |
|---|---|
| `0x006e7018` | `DirectInput8Create` |

### WINMM.dll（1）

| IAT VA | 函数 |
|---|---|
| `0x006e7308` | `timeGetTime` |

### GDI32.dll（1）

| IAT VA | 函数 |
|---|---|
| `0x006e7020` | `GetStockObject` |

### dbghelp.dll（1）

| IAT VA | 函数 |
|---|---|
| `0x006e741c` | `MiniDumpWriteDump` |

## 4. 关键 IAT 地址

* `0x006e7374` = `d3d9.dll!Direct3DCreate9`　— D3D9 建对象
* `0x006e7018` = `DINPUT8.dll!DirectInput8Create`　— DirectInput 建对象
* `0x006e7308` = `WINMM.dll!timeGetTime`　— 毫秒时间
* `0x006e71c4` = `KERNEL32.dll!GetModuleHandleA`　— GetModuleHandleA —— 0x781DC8 存的是它返回的 hInstance（**非设备指针**）
* `0x006e7380` = `d3dx9_30.dll!D3DXMatrixMultiply`　— D3DXMatrixMultiply
* `0x006e73f8` = `d3dx9_30.dll!D3DXVec3Transform`　— D3DXVec3Transform
* `0x006e73ac` = `d3dx9_30.dll!D3DXVec4Transform`　— D3DXVec4Transform
* `0x006e7390` = `d3dx9_30.dll!D3DXMatrixInverse`　— D3DXMatrixInverse
* `0x006e73e0` = `d3dx9_30.dll!D3DXAssembleShader`　— D3DXAssembleShader
* `0x006e71dc` = `KERNEL32.dll!QueryPerformanceFrequency`　— QueryPerformanceFrequency
* `0x006e71e0` = `KERNEL32.dll!QueryPerformanceCounter`　— QueryPerformanceCounter

## 5. ★★★ 导入跳转桩表（IAT thunks）—— 本 EXE 的调用方式

**发现**：本 EXE **不直接** `call [IAT]`（全 `.text` 扫 `FF 15 <IAT>` 对 D3DX/D3D9 目标**零命中**），
而是每个导入函数对应一条 **6 字节桩**：

```asm
0x5f918a  jmp dword ptr [0x6e7374]     ; = d3d9.dll!Direct3DCreate9
0x5f9190  jmp dword ptr [0x6e7380]     ; = d3dx9_30.dll!D3DXMatrixMultiply
0x5f9196  jmp dword ptr [0x6e7384]     ; = ...
   …  连续排布，桩表位于 0x5F918A 起
```

**⇒ 内部代码一律 `call <桩地址>`**。因此「谁用了某外部函数」必须扫 `call <桩>`，**不能扫 IAT 地址**
（这正是早期多轮「扫导入零命中」的原因）。工具：`tools/thunks.py`（`--who-name` / `--list` / `--uses`），
桩目录已导出到 `out_import_thunks.csv`。

**规模**：94 条桩（`d3dx9_30` 39 · `fmodex` 36 · `fmod_event` 10 · `KERNEL32` 5 · `ole32`/`d3d9`/`DINPUT8`/`dbghelp` 各 1），
桩区 `0x5F918A–0x5F9260`；**总调用点 228 处**。其余导入（KERNEL32 129 条、USER32 41 条等）走直接 `call [IAT]`。

### 5.1 ★★★ 关键结论（实测）

| 导入 | 调用点 | 调用它的函数 | 结论 |
|---|---|---|---|
| `Direct3DCreate9` | 1 | `0x5026d0` | ★★★ **仅 `0x5026D0` 调用** = 渲染器单例 `0x781E80` 的构造函数 ⇒ **`0x781E80` 是 D3D9 渲染器/设备单例**（与 `docs/46` 互证） |
| `D3DXMatrixMultiply` | 41 | `0x502f70` · `0x51ff40` · `0x523360` · `0x5241f0` · `0x528420` · `0x5285fa` · `0x528975` · `0x528ff0` … | ★ 全部集中在 **渲染器簇 `0x502Fxx`、`0x51FFxx–0x539Fxx`** ⇒ D3DX 矩阵数学属渲染线，物理线不引用（与「物理用自有数学」一致） |
| `D3DXMatrixInverse` | 12 | `0x4ffa60` · `0x502f70` · `0x503360` · `0x5287d0` · `0x528ff0` · `0x52e7d0` · `0x5374e0` · `0x538210` | 渲染线（相机/法线矩阵求逆） |
| `D3DXVec3Normalize` | 3 | `0x539150` | 渲染线 |
| `D3DXCreateTeapot` | 1 | `0x508610` | 开发期占位模型（可忽略） |
| `D3DXAssembleShader` | 2 | `0x5303b0` · `0x5304a0` | ★★ **`0x5303B0` / `0x5304A0`** ⇒ **着色器在运行时由汇编文本编译**；`.vsh/.psh` 文本应从此二函数的上游找 |
| `D3DXAssembleShaderFromFileA` | 1 | `0x5304a0` | ★★ `0x5304A0` ⇒ 有「从文件加载 shader」的路径 ⇒ 磁盘上存在 shader 源文件 |
| `D3DXVec3Transform` | 2 | `0x538210` · `0x539150` | 渲染线少量使用 |
| `DirectInput8Create` | 1 | `0x56e300` | 输入线入口 |

### 5.2 使用最多的导入（前 18）

| 调用点 | 函数数 | 导入 |
|---|---|---|
| 41 | 14 | `d3dx9_30.dll!D3DXMatrixMultiply` |
| 12 | 8 | `d3dx9_30.dll!D3DXMatrixInverse` |
| 9 | 2 | `d3dx9_30.dll!D3DXSHRotate` |
| 9 | 7 | `fmodex.dll!?stop@Channel@FMOD@@QAG?AW4FMOD_RESULT@@XZ` |
| 8 | 7 | `d3dx9_30.dll!D3DXMatrixPerspectiveFovRH` |
| 7 | 4 | `d3dx9_30.dll!D3DXCreateTexture` |
| 6 | 5 | `d3dx9_30.dll!D3DXLoadSurfaceFromSurface` |
| 6 | 4 | `d3dx9_30.dll!D3DXMatrixTranspose` |
| 5 | 4 | `d3dx9_30.dll!D3DXVec4Transform` |
| 5 | 4 | `fmod_event.dll!?stop@Event@FMOD@@QAG?AW4FMOD_RESULT@@XZ` |
| 4 | 4 | `d3dx9_30.dll!D3DXFillTexture` |
| 4 | 4 | `d3dx9_30.dll!D3DXSaveTextureToFileA` |
| 4 | 4 | `fmodex.dll!?createSound@System@FMOD@@QAG?AW4FMOD_RESULT@@PBDIPAUFMOD_CREATESOUNDEXINFO@@PAPAVSound@2@@Z` |
| 3 | 1 | `d3dx9_30.dll!D3DXVec3Normalize` |
| 3 | 2 | `d3dx9_30.dll!D3DXPlaneNormalize` |
| 3 | 3 | `d3dx9_30.dll!D3DXCreateTorus` |
| 3 | 2 | `d3dx9_30.dll!D3DXMatrixLookAtRH` |
| 3 | 3 | `fmodex.dll!?setPaused@Channel@FMOD@@QAG?AW4FMOD_RESULT@@_N@Z` |
