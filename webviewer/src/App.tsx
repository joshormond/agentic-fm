import { useState, useEffect, useCallback, useRef } from 'preact/hooks';
import { Toolbar } from '@/ui/Toolbar';
import { StatusBar } from '@/ui/StatusBar';
import { EditorPanel } from '@/editor/EditorPanel';
import { XmlPreview } from '@/editor/xml-preview/XmlPreview';
import { ChatPanel } from '@/ai/chat/ChatPanel';
import { AISettings } from '@/ai/settings/AISettings';
import { LoadScriptDialog } from '@/ui/LoadScriptDialog';
import { LibraryPanel } from '@/ui/LibraryPanel';
import type { FMContext } from '@/context/types';
import { fetchContext, fetchSteps, fetchStepCatalog, fetchSettings, fetchDocs, validateSnippet, clipboardWrite, writeSandbox } from '@/api/client';
import type { StepInfo } from '@/api/client';
import type { StepCatalogEntry } from '@/converter/catalog-types';
import { hrToXml, loadCatalog } from '@/converter/hr-to-xml';
import { saveDraft, restoreDraft } from '@/autosave';
import { loadEditorMode, saveEditorMode, loadSavedPresetId, LIGHT_PRESETS, getThemeBackgrounds } from '@/editor/language/themes';
import { loadLayoutPrefsSync, saveLayoutPrefs, loadLayoutPrefsFromServer, hasLocalPrefs } from '@/layout-prefs';

function useSplitPane(defaultPct = 50, min = 20, max = 80, direction: 'horizontal' | 'vertical' = 'horizontal') {
  const [pct, setPct] = useState(defaultPct);
  const containerRef = useRef<HTMLDivElement>(null);

  const onDividerMouseDown = useCallback((e: MouseEvent) => {
    e.preventDefault();
    const container = containerRef.current;
    if (!container) return;

    const move = (me: MouseEvent) => {
      const rect = container.getBoundingClientRect();
      const newPct = direction === 'vertical'
        ? ((me.clientY - rect.top) / rect.height) * 100
        : ((me.clientX - rect.left) / rect.width) * 100;
      setPct(Math.min(max, Math.max(min, newPct)));
    };
    const up = () => {
      window.removeEventListener('mousemove', move);
      window.removeEventListener('mouseup', up);
    };
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', up);
  }, [min, max, direction]);

  return { pct, setPct, containerRef, onDividerMouseDown };
}

function useResizablePanel(defaultWidth: number, min: number, max: number) {
  const [width, setWidth] = useState(defaultWidth);

  const onDividerMouseDown = useCallback((e: MouseEvent) => {
    e.preventDefault();
    const startX = e.clientX;
    const startWidth = width;

    const move = (me: MouseEvent) => {
      const delta = me.clientX - startX;
      setWidth(Math.min(max, Math.max(min, startWidth + delta)));
    };
    const up = () => {
      window.removeEventListener('mousemove', move);
      window.removeEventListener('mouseup', up);
    };
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', up);
  }, [width, min, max]);

  return { width, setWidth, onDividerMouseDown };
}

export function App() {
  // Load layout prefs once on mount — localStorage is sync so no flash
  const [initialPrefs] = useState(loadLayoutPrefsSync);

  const [context, setContext] = useState<FMContext | null>(null);
  const [generatedAt, setGeneratedAt] = useState<string | undefined>(undefined);
  const [status, setStatus] = useState('Ready');
  const [editorContent, setEditorContent] = useState(sampleScript);
  const [scriptName, setScriptName] = useState('');
  const [showXmlPreview, setShowXmlPreview] = useState(initialPrefs.showXmlPreview);
  const [showChat, setShowChat] = useState(initialPrefs.showChat);
  const [showSettings, setShowSettings] = useState(false);
  const [showLoadScript, setShowLoadScript] = useState(false);
  const [showLibrary, setShowLibrary] = useState(initialPrefs.showLibrary);
  const [steps, setSteps] = useState<StepInfo[]>([]);
  const [catalog, setCatalog] = useState<StepCatalogEntry[]>([]);
  const [promptMarker, setPromptMarker] = useState('prompt');
  const [codingConventions, setCodingConventions] = useState('');
  const [knowledgeDocs, setKnowledgeDocs] = useState('');
  const [chatKey, setChatKey] = useState(0);
  const [editorMode, setEditorMode] = useState<'script' | 'calc'>(loadEditorMode);
  const [presetId, setPresetId] = useState(() => loadSavedPresetId());
  const isLightTheme = LIGHT_PRESETS.has(presetId);
  const themeBg = getThemeBackgrounds(presetId);
  const scriptNameRef = useRef('');
  const editorContentRef = useRef(editorContent);
  const mainSplit = useSplitPane(initialPrefs.editorPct);
  const editorXmlSplit = useSplitPane(initialPrefs.editorXmlPct, 15, 85, 'vertical');
  const library = useResizablePanel(initialPrefs.libraryWidth, 140, 480);

  // Keep refs in sync so callbacks always have the latest values
  scriptNameRef.current = scriptName;
  editorContentRef.current = editorContent;

  useEffect(() => {
    fetchContext().then(ctx => {
      setContext(ctx);
      setGeneratedAt(ctx.generated_at);
    }).catch(() => {
      setStatus('No CONTEXT.json found');
    });
    fetchSteps().then(setSteps).catch(() => {});
    fetchStepCatalog().then(cat => {
      setCatalog(cat);
      loadCatalog(cat);
    }).catch(() => {});
    fetchSettings().then(s => setPromptMarker(s.promptMarker || 'prompt')).catch(() => {});
    fetchDocs().then(d => {
      setCodingConventions(d.conventions);
      setKnowledgeDocs(d.knowledge);
    }).catch(() => {});
  }, []);

  // Restore draft on mount — skip if it's just the sample boilerplate
  useEffect(() => {
    restoreDraft().then(draft => {
      if (draft && draft.hr.trim() !== sampleScript.trim()) {
        setEditorContent(draft.hr);
        if (draft.scriptName) {
          setScriptName(draft.scriptName);
          setStatus(`Restored draft: ${draft.scriptName}`);
        } else {
          setStatus('Restored draft');
        }
      }
    }).catch(() => {});
  }, []);

  // Auto-save on editor changes (debounced via saveDraft)
  useEffect(() => {
    saveDraft(editorContent, scriptNameRef.current);
  }, [editorContent]);

  // Persist layout prefs whenever any panel visibility or size changes
  useEffect(() => {
    saveLayoutPrefs({
      showXmlPreview,
      showChat,
      showLibrary,
      editorPct: mainSplit.pct,
      editorXmlPct: editorXmlSplit.pct,
      libraryWidth: library.width,
    });
  }, [showXmlPreview, showChat, showLibrary, mainSplit.pct, editorXmlSplit.pct, library.width]);

  // Server fallback: restore layout prefs when localStorage has no saved state
  useEffect(() => {
    if (hasLocalPrefs()) return;
    loadLayoutPrefsFromServer().then(prefs => {
      if (!prefs) return;
      setShowXmlPreview(prefs.showXmlPreview);
      setShowChat(prefs.showChat);
      setShowLibrary(prefs.showLibrary);
      mainSplit.setPct(prefs.editorPct);
      editorXmlSplit.setPct(prefs.editorXmlPct);
      library.setWidth(prefs.libraryWidth);
    });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Expose global callbacks for FileMaker JS bridge
  useEffect(() => {
    (window as any).pushContext = (jsonString: string) => {
      try {
        const ctx = JSON.parse(jsonString) as FMContext;
        setContext(ctx);
        setGeneratedAt(ctx.generated_at);
        setStatus(`Context loaded: ${ctx.solution ?? 'unknown'}`);
      } catch {
        setStatus('Error parsing context');
      }
    };

    (window as any).loadScript = (content: string) => {
      setEditorContent(content);
    };

    return () => {
      delete (window as any).pushContext;
      delete (window as any).loadScript;
      delete (window as any).triggerAppAction;
    };
  }, []);

  const handleNewScript = useCallback(async () => {
    const name = prompt('Script name:');
    if (!name) return;
    const hr = `# ${name} - 00\n`;
    const { xml } = hrToXml(hr, context);
    const filename = `${name} - 00.xml`;
    setEditorContent(hr);
    setScriptName(name);
    try {
      await writeSandbox(filename, xml);
      setStatus(`New script: ${name}`);
    } catch {
      setStatus(`New script: ${name} (failed to save file)`);
    }
  }, [context]);

  const handleValidate = useCallback(async () => {
    setStatus('Validating...');
    const { xml, errors } = hrToXml(editorContent, context);
    if (errors.length > 0) {
      console.warn('[validate] conversion errors:', errors);
      setStatus(`Conversion: ${errors.map((e: { line: number; message: string }) => `L${e.line}: ${e.message}`).join('; ')}`);
      return;
    }
    try {
      const result = await validateSnippet(xml);
      if (result.valid) {
        setStatus('Validation passed');
      } else {
        setStatus(`Validation: ${result.errors.join('; ')}`);
      }
    } catch {
      setStatus('Validation failed (server error)');
    }
  }, [editorContent, context]);

  const handleClipboard = useCallback(async () => {
    setStatus('Converting & copying to clipboard...');
    const { xml, errors } = hrToXml(editorContent, context);
    if (errors.length > 0) {
      setStatus(`Cannot copy: ${errors.length} conversion error(s)`);
      return;
    }
    try {
      const result = await clipboardWrite(xml);
      if (result.ok) {
        setStatus('Copied to clipboard — ready to paste into FileMaker');
        window.onClipboardReady?.();
      } else {
        setStatus(`Clipboard error: ${result.error}`);
      }
    } catch {
      setStatus('Clipboard write failed (server error)');
    }
  }, [editorContent, context]);

  const handleInsertScript = useCallback((script: string) => {
    setEditorContent(script);
    setScriptName('');
    setStatus('Script inserted from AI');
  }, []);

  const [showInsertWarning, setShowInsertWarning] = useState(false);

  const handleLibraryInsert = useCallback((content: string) => {
    const inserted = (window as any).insertAtEditorCursor?.(content) ?? false;
    if (!inserted) {
      setShowInsertWarning(true);
    }
  }, []);

  const handleScriptLoaded = useCallback((hr: string, name: string, options: { resetChat: boolean }) => {
    setEditorContent(hr);
    setScriptName(name);
    setShowLoadScript(false);
    setStatus(`Loaded: ${name}`);
    if (options.resetChat) setChatKey(k => k + 1);
  }, []);

  // Expose app-level toolbar actions for FileMaker JS bridge (agfm.* action IDs)
  useEffect(() => {
    (window as any).triggerAppAction = (actionId: string) => {
      switch (actionId) {
        case 'agfm.newScript':       handleNewScript(); break;
        case 'agfm.validate':        handleValidate(); break;
        case 'agfm.clipboard':       handleClipboard(); break;
        case 'agfm.loadScript':      setShowLoadScript(true); break;
        case 'agfm.toggleXmlPreview': setShowXmlPreview(v => !v); break;
        case 'agfm.toggleChat':      setShowChat(v => !v); break;
        case 'agfm.toggleLibrary':   setShowLibrary(v => !v); break;
      }
    };
  }, [handleNewScript, handleValidate, handleClipboard]);

  return (
    <div
      class="flex flex-col h-full"
      data-ui-theme={isLightTheme ? 'light' : 'dark'}
      style={{ '--color-neutral-900': themeBg.panel, '--color-neutral-800': themeBg.chrome } as any}
    >
      <Toolbar
        context={context}
        showXmlPreview={showXmlPreview}
        showChat={showChat}
        showLibrary={showLibrary}
        editorMode={editorMode}
        onToggleXmlPreview={() => setShowXmlPreview(v => !v)}
        onToggleChat={() => setShowChat(v => !v)}
        onToggleLibrary={() => setShowLibrary(v => !v)}
        onRefreshContext={() => {
          fetchContext().then(setContext).catch(() => {
            setStatus('Failed to refresh context');
          });
        }}
        onNewScript={handleNewScript}
        onValidate={handleValidate}
        onClipboard={handleClipboard}
        onLoadScript={() => setShowLoadScript(true)}
        onOpenSettings={() => setShowSettings(true)}
        onSetEditorMode={(mode) => { setEditorMode(mode); saveEditorMode(mode); }}
      />
      <div class="flex-1 min-h-0 flex">
        {showLibrary && (
          <>
            <div style={{ width: library.width, flexShrink: 0 }} class="h-full min-w-0 overflow-hidden">
              <LibraryPanel
                onInsert={handleLibraryInsert}
                onStatus={setStatus}
                getEditorContent={() => editorContentRef.current}
                getEditorSelection={() => (window as any).getEditorSelection?.() ?? null}
              />
            </div>
            <div
              class="w-1 shrink-0 h-full bg-neutral-700 hover:bg-blue-500 cursor-col-resize transition-colors"
              onMouseDown={library.onDividerMouseDown}
            />
          </>
        )}
        {/* Main resizable area: left column | chat */}
        <div ref={mainSplit.containerRef} class="flex-1 min-h-0 h-full flex">
          {/* Left column: editor stacked above optional XML preview */}
          <div
            ref={editorXmlSplit.containerRef}
            style={showChat ? { flexBasis: `${mainSplit.pct}%`, flexShrink: 0, flexGrow: 0, minWidth: 0 } : undefined}
            class={`${showChat ? '' : 'flex-1'} h-full min-w-0 flex flex-col`}
          >
            {/* Editor */}
            <div
              style={showXmlPreview ? { flexBasis: `${editorXmlSplit.pct}%`, flexShrink: 0, flexGrow: 0, minHeight: 0 } : undefined}
              class={`${showXmlPreview ? '' : 'flex-1'} w-full min-h-0`}
            >
              <EditorPanel
                value={editorContent}
                onChange={setEditorContent}
                context={context}
              />
            </div>

            {/* Horizontal divider between editor and XML preview */}
            {showXmlPreview && (
              <div
                class="h-1 shrink-0 w-full bg-neutral-700 hover:bg-blue-500 cursor-row-resize transition-colors"
                onMouseDown={editorXmlSplit.onDividerMouseDown}
              />
            )}

            {/* XML preview below editor */}
            {showXmlPreview && (
              <div class="flex-1 w-full min-h-0">
                <XmlPreview hrText={editorContent} context={context} />
              </div>
            )}
          </div>

          {/* Vertical divider between left column and chat */}
          {showChat && (
            <div
              class="w-1 shrink-0 h-full bg-neutral-700 hover:bg-blue-500 cursor-col-resize transition-colors"
              onMouseDown={mainSplit.onDividerMouseDown}
            />
          )}

          {/* Chat panel */}
          {showChat && (
            <div class="flex-1 min-w-0 h-full">
              <ChatPanel
                key={chatKey}
                context={context}
                steps={steps}
                catalog={catalog}
                editorContent={editorContent}
                promptMarker={promptMarker}
                codingConventions={codingConventions}
                knowledgeDocs={knowledgeDocs}
                onInsertScript={handleInsertScript}
                onClearChat={() => setChatKey(k => k + 1)}
              />
            </div>
          )}
        </div>
      </div>
      <StatusBar
        status={status}
        solution={context?.solution}
        layout={context?.current_layout?.name}
        generatedAt={generatedAt}
      />

      {showSettings && <AISettings onClose={() => setShowSettings(false)} onPresetChange={setPresetId} />}
      {showLoadScript && (
        <LoadScriptDialog
          context={context}
          editorContent={editorContent}
          onLoad={handleScriptLoaded}
          onContextUpdate={setContext}
          onClose={() => setShowLoadScript(false)}
        />
      )}

      {showInsertWarning && (
        <div class="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div class="bg-neutral-800 rounded-lg shadow-xl w-80 max-w-[90vw]">
            <div class="flex items-center justify-between px-4 py-3 border-b border-neutral-700">
              <h2 class="text-sm font-semibold text-neutral-200">No cursor position</h2>
              <button
                onClick={() => setShowInsertWarning(false)}
                class="text-neutral-400 hover:text-neutral-200 text-lg leading-none"
              >
                &times;
              </button>
            </div>
            <div class="px-4 py-4 text-xs text-neutral-300 leading-relaxed">
              Click inside the editor first to establish a cursor position, then insert from the library.
            </div>
            <div class="flex justify-end px-4 py-3 border-t border-neutral-700">
              <button
                onClick={() => setShowInsertWarning(false)}
                class="px-3 py-1 rounded text-xs bg-blue-700 hover:bg-blue-600 text-white transition-colors"
              >
                OK
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

const sampleScript = `# New Line Item for Invoice
Set Error Capture [ On ]
Allow User Abort [ Off ]
Freeze Window

Set Variable [ $invoiceId ; Invoices::PrimaryKey ]

If [ IsEmpty ( $invoiceId ) ]
    Show Custom Dialog [ "Error" ; "No invoice selected." ]
    Exit Script [ Result: False ]
End If

Go to Layout [ "Card Line Item Details" ]
New Record/Request
Set Field [ Line Items::ForeignKeyInvoice ; $invoiceId ]
Commit Records/Requests [ With dialog: Off ]
`;
