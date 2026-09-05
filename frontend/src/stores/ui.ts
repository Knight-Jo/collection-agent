import { create } from "zustand";

type PanelKind = "sources" | "materials";

interface UiState {
  panel: PanelKind;
  open: boolean;
  setPanel: (panel: PanelKind) => void;
  toggle: () => void;
}

export const useUiStore = create<UiState>((set) => ({
  panel: "materials",
  open: true,
  setPanel: (panel) => set({ panel, open: true }),
  toggle: () => set((state) => ({ open: !state.open })),
}));
