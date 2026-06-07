#pragma once

#include "KumiAgent.h"

/**
 * Kumi Edge — UE5 tool registration
 *
 * Call InitKumi() early in your game lifecycle (e.g. from GameInstance::Init
 * or a custom subsystem).
 *
 * Setup:
 * 1. Copy KumiSDK/ module into your project's Source/ directory
 * 2. Add "KumiSDK" to your .Build.cs PublicDependencyModuleNames
 * 3. Regenerate project files
 */

// ── Connection (edit here, or set in .env) ──

static const TCHAR* KumiConnectionCode = TEXT("kumi-lan_...");  // from `kumi --server`
static const TCHAR* KumiEdgeName = TEXT("My UE5 Game");

FKumiAgent* InitKumi();
