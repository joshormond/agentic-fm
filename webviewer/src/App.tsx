import { useState, useEffect, useCallback, useRef } from 'preact/hooks';
import { Toolbar } from '@/ui/Toolbar';
import { StatusBar } from '@/ui/StatusBar';
import { EditorPanel } from '@/editor/EditorPanel';
import { XmlPreview } from '@/editor/xml-preview/XmlPreview';
import { ChatPanel } from '@/ai/chat/ChatPanel';
import { AISettings } from '@/ai/settings/AISettings';
import { LoadScriptDialog } from '@/ui/LoadScriptDialog';
import type { FMContext } from '@/context/types';
import { fetchContext, fetchSteps, fetchStepCatalog, fetchSettings, fetchDocs, validateSnippet, clipboardWrite, writeSandbox } from '@/api/client';
import type { StepInfo } from '@/api/client';
import type { StepCatalogEntry } from '@/converter/catalog-types';
import { hrToXml, loadCatalog } from '@/converter/hr-to-xml';
import { saveDraft, restoreDraft } from '@/autosave';

export function App() {
  const [context, setContext] = useState<FMContext | null>(null);
  const [status, setStatus] = useState('Ready');
  const [editorContent, setEditorContent] = useState(sampleScript);
  const [scriptName, setScriptName] = useState('');
  const [showXmlPreview, setShowXmlPreview] = useState(false);
  const [showChat, setShowChat] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [showLoadScript, setShowLoadScript] = useState(false);
  const [steps, setSteps] = useState<StepInfo[]>([]);
  const [catalog, setCatalog] = useState<StepCatalogEntry[]>([]);
  const [promptMarker, setPromptMarker] = useState('prompt');
  const [codingConventions, setCodingConventions] = useState('');
  const [knowledgeDocs, setKnowledgeDocs] = useState('');
  const [chatKey, setChatKey] = useState(0);
  const scriptNameRef = useRef('');

  // Keep ref in sync so the autosave effect always has the latest name
  scriptNameRef.current = scriptName;

  useEffect(() => {
    fetchContext().then(setContext).catch(() => {
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

  // Expose global callbacks for FileMaker JS bridge
  useEffect(() => {
    (window as any).pushContext = (jsonString: string) => {
      try {
        const ctx = JSON.parse(jsonString) as FMContext;
        setContext(ctx);
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
      }
    };
  }, [handleNewScript, handleValidate, handleClipboard]);

  return (
    <div class="flex flex-col h-full">
      <Toolbar
        context={context}
        showXmlPreview={showXmlPreview}
        showChat={showChat}
        onToggleXmlPreview={() => setShowXmlPreview(v => !v)}
        onToggleChat={() => setShowChat(v => !v)}
        onRefreshContext={() => {
          fetchContext().then(setContext).catch(() => {
            setStatus('Failed to refresh context');
          });
        }}
        onClearChat={() => setChatKey(k => k + 1)}
        onNewScript={handleNewScript}
        onValidate={handleValidate}
        onClipboard={handleClipboard}
        onLoadScript={() => setShowLoadScript(true)}
        onOpenSettings={() => setShowSettings(true)}
      />
      <div class="flex-1 min-h-0 flex">
        <div class={`${showXmlPreview || showChat ? 'w-1/2' : 'w-full'} min-w-0 h-full`}>
          <EditorPanel
            value={editorContent}
            onChange={setEditorContent}
            context={context}
          />
        </div>
        {showXmlPreview && !showChat && (
          <div class="w-1/2 min-w-0 h-full">
            <XmlPreview hrText={editorContent} context={context} />
          </div>
        )}
        {showChat && (
          <div class={showXmlPreview ? 'w-1/2 min-w-0 h-full flex' : 'w-1/2 min-w-0 h-full'}>
            {showXmlPreview && (
              <div class="w-1/2 min-w-0 h-full">
                <XmlPreview hrText={editorContent} context={context} />
              </div>
            )}
            <div class={showXmlPreview ? 'w-1/2 min-w-0 h-full' : 'w-full h-full'}>
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
              />
            </div>
          </div>
        )}
      </div>
      <StatusBar
        status={status}
        solution={context?.solution}
        layout={context?.current_layout?.name}
      />

      {showSettings && <AISettings onClose={() => setShowSettings(false)} />}
      {showLoadScript && (
        <LoadScriptDialog
          context={context}
          editorContent={editorContent}
          onLoad={handleScriptLoaded}
          onContextUpdate={setContext}
          onClose={() => setShowLoadScript(false)}
        />
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
