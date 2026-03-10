import type * as monaco from 'monaco-editor';

export interface ThemeColors {
  comments: string;
  controlFlow: string;
  scriptSteps: string;
  variables: string;
  globals: string;
  fields: string;
  strings: string;
  functions: string;
  constants: string;
  numbers: string;
  operators: string;
  brackets: string;
}

export interface ThemePreset {
  id: string;
  name: string;
  colors: ThemeColors;
}

export const DEFAULT_COLORS: ThemeColors = {
  comments: '#6A9955',
  controlFlow: '#C586C0',
  scriptSteps: '#569CD6',
  variables: '#9CDCFE',
  globals: '#4EC9B0',
  fields: '#DCDCAA',
  strings: '#CE9178',
  functions: '#DCDCAA',
  constants: '#569CD6',
  numbers: '#B5CEA8',
  operators: '#D4D4D4',
  brackets: '#FFD700',
};

export const THEME_PRESETS: ThemePreset[] = [
  {
    id: 'default_dark',
    name: 'Default Dark',
    colors: DEFAULT_COLORS,
  },
  {
    id: 'monokai_dark',
    name: 'Monokai Dark',
    colors: {
      comments: '#75715E',
      controlFlow: '#F92672',
      scriptSteps: '#66D9EF',
      variables: '#FD971F',
      globals: '#A6E22E',
      fields: '#E6DB74',
      strings: '#E6DB74',
      functions: '#A6E22E',
      constants: '#AE81FF',
      numbers: '#AE81FF',
      operators: '#F8F8F2',
      brackets: '#F8F8F2',
    },
  },
  {
    id: 'github_dark',
    name: 'GitHub Dark',
    colors: {
      comments: '#8B949E',
      controlFlow: '#FF7B72',
      scriptSteps: '#79C0FF',
      variables: '#FFA657',
      globals: '#3DC9B0',
      fields: '#E3B341',
      strings: '#A5D6FF',
      functions: '#D2A8FF',
      constants: '#79C0FF',
      numbers: '#79C0FF',
      operators: '#C9D1D9',
      brackets: '#C9D1D9',
    },
  },
  {
    id: 'solarized_dark',
    name: 'Solarized Dark',
    colors: {
      comments: '#586E75',
      controlFlow: '#859900',
      scriptSteps: '#268BD2',
      variables: '#B58900',
      globals: '#2AA198',
      fields: '#CB4B16',
      strings: '#2AA198',
      functions: '#268BD2',
      constants: '#D33682',
      numbers: '#D33682',
      operators: '#839496',
      brackets: '#657B83',
    },
  },
  {
    id: 'solarized_light',
    name: 'Solarized Light',
    colors: {
      comments: '#93A1A1',
      controlFlow: '#859900',
      scriptSteps: '#268BD2',
      variables: '#B58900',
      globals: '#2AA198',
      fields: '#CB4B16',
      strings: '#2AA198',
      functions: '#268BD2',
      constants: '#D33682',
      numbers: '#D33682',
      operators: '#657B83',
      brackets: '#073642',
    },
  },
];

export function buildMonacoTheme(colors: ThemeColors, isLight = false): monaco.editor.IStandaloneThemeData {
  return {
    base: isLight ? 'vs' : 'vs-dark',
    inherit: true,
    rules: [
      { token: 'comment', foreground: colors.comments.replace('#', ''), fontStyle: 'italic' },
      { token: 'comment.disabled', foreground: colors.comments.replace('#', ''), fontStyle: 'italic strikethrough' },
      { token: 'keyword.control', foreground: colors.controlFlow.replace('#', ''), fontStyle: 'bold' },
      { token: 'keyword.step', foreground: colors.scriptSteps.replace('#', '') },
      { token: 'variable.local', foreground: colors.variables.replace('#', '') },
      { token: 'variable.let', foreground: colors.variables.replace('#', '') },
      { token: 'variable.global', foreground: colors.globals.replace('#', ''), fontStyle: 'bold' },
      { token: 'field.reference', foreground: colors.fields.replace('#', '') },
      { token: 'string', foreground: colors.strings.replace('#', '') },
      { token: 'function', foreground: colors.functions.replace('#', '') },
      { token: 'constant', foreground: colors.constants.replace('#', ''), fontStyle: 'bold' },
      { token: 'number', foreground: colors.numbers.replace('#', '') },
      { token: 'operator', foreground: colors.operators.replace('#', '') },
      { token: 'delimiter', foreground: colors.operators.replace('#', '') },
      { token: 'delimiter.bracket', foreground: colors.brackets.replace('#', '') },
      { token: 'delimiter.paren', foreground: colors.operators.replace('#', '') },
      { token: 'parameter.label', foreground: '808080' },
    ],
    colors: isLight
      ? {
          'editor.background': '#FDF6E3',
          'editor.foreground': '#657B83',
          'editor.lineHighlightBackground': '#EEE8D5',
          'editorCursor.foreground': '#586E75',
          'editor.selectionBackground': '#D3CBB1',
          'editor.inactiveSelectionBackground': '#E8E0CC',
        }
      : {
          'editor.background': '#1E1E1E',
          'editor.foreground': '#D4D4D4',
          'editor.lineHighlightBackground': '#2A2D2E',
          'editorCursor.foreground': '#AEAFAD',
          'editor.selectionBackground': '#264F78',
          'editor.inactiveSelectionBackground': '#3A3D41',
        },
  };
}

export const LIGHT_PRESETS = new Set(['solarized_light']);

/** Returns the panel body and chrome (toolbar/header) background colours for a preset,
 *  matching the exact values Monaco uses for editor.background. */
export function getThemeBackgrounds(presetId: string): { panel: string; chrome: string } {
  if (LIGHT_PRESETS.has(presetId)) {
    return { panel: '#FDF6E3', chrome: '#EEE8D5' };
  }
  return { panel: '#1E1E1E', chrome: '#252526' };
}

export function loadSavedTheme(): ThemeColors {
  try {
    const saved = localStorage.getItem('fm-editor-theme');
    if (!saved) return DEFAULT_COLORS;
    const parsed = JSON.parse(saved) as { preset?: string; custom?: Partial<ThemeColors> };
    const preset = THEME_PRESETS.find(p => p.id === parsed.preset) ?? THEME_PRESETS[0];
    return { ...preset.colors, ...(parsed.custom ?? {}) };
  } catch {
    return DEFAULT_COLORS;
  }
}

export function loadSavedPresetId(): string {
  try {
    const saved = localStorage.getItem('fm-editor-theme');
    if (!saved) return 'default_dark';
    const parsed = JSON.parse(saved) as { preset?: string };
    return parsed.preset ?? 'default_dark';
  } catch {
    return 'default_dark';
  }
}

export function loadSavedCustomColors(): Partial<ThemeColors> {
  try {
    const saved = localStorage.getItem('fm-editor-theme');
    if (!saved) return {};
    const parsed = JSON.parse(saved) as { custom?: Partial<ThemeColors> };
    return parsed.custom ?? {};
  } catch {
    return {};
  }
}

export function saveTheme(
  monacoInstance: typeof import('monaco-editor'),
  preset: string,
  custom?: Partial<ThemeColors>,
): void {
  localStorage.setItem('fm-editor-theme', JSON.stringify({ preset, custom: custom ?? {} }));
  const presetObj = THEME_PRESETS.find(p => p.id === preset) ?? THEME_PRESETS[0];
  const colors = { ...presetObj.colors, ...(custom ?? {}) };
  monacoInstance.editor.defineTheme('filemaker-dark', buildMonacoTheme(colors, LIGHT_PRESETS.has(preset)));
  monacoInstance.editor.setTheme('filemaker-dark');
}

export function loadEditorMode(): 'script' | 'calc' {
  try {
    const saved = localStorage.getItem('fm-editor-mode');
    return saved === 'calc' ? 'calc' : 'script';
  } catch {
    return 'script';
  }
}

export function saveEditorMode(mode: 'script' | 'calc'): void {
  localStorage.setItem('fm-editor-mode', mode);
}
