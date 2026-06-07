"""Shared UI constants: default server URL, injected scripts, theme CSS, palette."""

DEFAULT_SERVER_URL = "http://127.0.0.1:8000"

SCROLL_SCRIPT = """
(function(){
    function init(){
        var el=document.getElementById('msg-scroll');
        if(!el){setTimeout(init,300);return}
        new MutationObserver(function(){
            if(el.scrollHeight-el.scrollTop-el.clientHeight<250)
                el.scrollTop=el.scrollHeight;
        }).observe(el,{childList:true,subtree:true,characterData:true});
    }
    if(document.readyState==='loading')
        document.addEventListener('DOMContentLoaded',init);
    else init();
})();
"""

TEXTAREA_SCRIPT = """
(function(){
    var composing=new WeakMap();
    var lastSendAt=0;
    function inComposer(t){
        if(!t||!t.closest)return false;
        if(t.closest('#yumi_chat_drop')||t.closest('[data-yumi-chat-input]'))return true;
        var w=document.getElementById('chat-input');
        return !!(w&&w.contains(t));
    }
    function imeActive(e,t){
        if(e&&(e.isComposing===true))return true;
        if(e&&e.keyCode===229)return true;
        if(e&&e.which===229)return true;
        try{
            var n=e&&e.nativeEvent;
            if(n&&n.isComposing)return true;
            if(n&&n.keyCode===229)return true;
        }catch(x){}
        return t&&composing.get(t)===true;
    }
    function clickSend(){
        var btn=document.getElementById('send-btn');
        if(btn&&!btn.disabled)btn.click();
    }
    function safeSend(){
        var now=Date.now();
        if(now-lastSendAt<120)return;
        lastSendAt=now;
        setTimeout(clickSend,0);
    }
    document.addEventListener('compositionstart',function(e){
        var t=e.target;
        if(t&&t.tagName&&t.tagName.toLowerCase()==='textarea'&&inComposer(t))
            composing.set(t,true);
    },true);
    document.addEventListener('compositionend',function(e){
        var t=e.target;
        if(t&&t.tagName&&t.tagName.toLowerCase()==='textarea')
            composing.set(t,false);
    },true);
    // Chrome (incl. Mac IME): ``beforeinput``/``insertLineBreak`` is the clean signal for
    // "Enter would insert a newline"; use with Shift+Enter still ``insertLineBreak`` but shiftKey set.
    function onBeforeInput(e){
        if(e.inputType!=='insertLineBreak')return;
        if(e.shiftKey)return;
        var t=e.target;
        if(!t||t.tagName.toLowerCase()!=='textarea')return;
        if(!inComposer(t))return;
        if(imeActive(e,t))return;
        e.preventDefault();
        safeSend();
    }
    function onDocKeyDown(e){
        if(e.shiftKey)return;
        var k=e.key||'';
        var c=e.code||'';
        if(k!=='Enter'&&c!=='Enter'&&c!=='NumpadEnter')return;
        var t=e.target;
        if(!t||!t.tagName||t.tagName.toLowerCase()!=='textarea')return;
        if(!inComposer(t))return;
        if(imeActive(e,t))return;
        e.preventDefault();
        safeSend();
    }
    function onDocInput(e){
        var t=e.target;
        if(!t||!t.tagName||t.tagName.toLowerCase()!=='textarea')return;
        if(!inComposer(t))return;
        t.style.height='auto';
        t.style.height=Math.min(t.scrollHeight,160)+'px';
    }
    if(typeof document!=='undefined'&&'onbeforeinput'in document){
        document.addEventListener('beforeinput',onBeforeInput,true);
    }
    document.addEventListener('keydown',onDocKeyDown,true);
    document.addEventListener('input',onDocInput,true);
})();
"""

# ``#chat-input`` may be a DebounceInput wrapper; the real control is the inner ``textarea``.
CHAT_INPUT_RESIZE_FOCUS_JS = (
    "var ta=(function(){var n=document.getElementById('chat-input');"
    "if(!n)return null;"
    "if(n.tagName&&n.tagName.toLowerCase()==='textarea')return n;"
    "return n.querySelector?n.querySelector('textarea'):null;}());"
    "if(ta){ta.style.height='auto';ta.style.height=Math.min(ta.scrollHeight,160)+'px';ta.focus();}"
)

CHAT_INPUT_RESET_HEIGHT_JS = (
    "var ta=(function(){var n=document.getElementById('chat-input');"
    "if(!n)return null;"
    "if(n.tagName&&n.tagName.toLowerCase()==='textarea')return n;"
    "return n.querySelector?n.querySelector('textarea'):null;}());"
    "if(ta){ta.style.height='auto';}"
)

_TIMER_POLL_JS = "new Promise(function(r){setTimeout(function(){r('poll')},3000)})"

# Monitor page: refresh topology + traces (Topology v2 light polling).
_MONITOR_POLL_JS = "new Promise(function(r){setTimeout(function(){r('m')},4500)})"

CUSTOM_CSS = """
:root{
    --bg-page:#ffffff;--bg-surface:#f8fafc;--bg-card:#ffffff;
    --bg-hover:#f1f5f9;--text-1:#0f172a;--text-2:#64748b;
    --text-3:#94a3b8;--border:#e2e8f0;--border-hover:#cbd5e1;
    --accent-soft:#eef2ff;--error-bg:#fef2f2;
    --code-bg:#1e293b;--tool-bg:#f1f5f9;--tool-text:#64748b;
    --heading:#1e293b;--shadow-sm:0 1px 2px rgba(0,0,0,.04);
    --shadow-md:0 2px 8px rgba(0,0,0,.06);
}
.dark{
    --bg-page:#09090b;--bg-surface:#111113;--bg-card:#18181b;
    --bg-hover:#1c1c1f;--text-1:#f4f4f5;--text-2:#a1a1aa;
    --text-3:#52525b;--border:#27272a;--border-hover:#3f3f46;
    --accent-soft:#1e1b4b;--error-bg:#451a1a;
    --code-bg:#111113;--tool-bg:#1c1c1f;--tool-text:#a1a1aa;
    --heading:#e4e4e7;--shadow-sm:0 1px 2px rgba(0,0,0,.2);
    --shadow-md:0 2px 8px rgba(0,0,0,.3);
}
*{box-sizing:border-box}
body{font-family:'Inter',system-ui,-apple-system,sans-serif;-webkit-font-smoothing:antialiased}
@keyframes cursor-blink{0%,50%{opacity:1}51%,100%{opacity:0}}
.cursor-blink{display:inline-block;animation:cursor-blink 1s step-end infinite;margin-left:2px}
.msg-actions{opacity:0;transition:opacity .15s}
.msg-row:hover .msg-actions{opacity:1}
#chat-input,#chat-input textarea{font-family:'Inter',system-ui,-apple-system,sans-serif}
#chat-input textarea{
    border-color:var(--border)!important;
    box-shadow:var(--shadow-sm)!important;
    transition:border-color .15s,box-shadow .15s!important;
}
#chat-input textarea:focus{
    border-color:#6366f1!important;
    box-shadow:0 0 0 3px rgba(99,102,241,.12)!important;
}
#chat-input textarea:disabled{opacity:.5;cursor:not-allowed}
#chat-input textarea::placeholder{color:var(--text-3)}
::-webkit-scrollbar{width:6px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px}
::-webkit-scrollbar-thumb:hover{background:var(--border-hover)}
"""

SB_BG = "#0f172a"
SB_HOVER = "#1e293b"
SB_TEXT = "#94a3b8"
SB_TEXT_HI = "#f1f5f9"
SB_BORDER = "#1e293b"
ACCENT = "#6366f1"
