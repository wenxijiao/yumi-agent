#pragma once

#include "YumiAgent.h"

/**
 * Yumi Edge — UE5 tool registration
 *
 * Call InitYumi() early in your game lifecycle (e.g. from GameInstance::Init
 * or a custom subsystem).
 *
 * Setup:
 * 1. Copy YumiSDK/ module into your project's Source/ directory
 * 2. Add "YumiSDK" to your .Build.cs PublicDependencyModuleNames
 * 3. Regenerate project files
 */

// ── Connection (edit here, or set in .env) ──

static const TCHAR* YumiConnectionCode = TEXT("yumi-lan_...");  // from `yumi --server`
static const TCHAR* YumiEdgeName = TEXT("My UE5 Game");

FYumiAgent* InitYumi();
