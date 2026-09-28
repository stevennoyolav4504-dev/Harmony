"""REV.06 brand colors mapped to readable desktop controls."""
import tkinter.font as tkfont

BLUE = "#07BAEE"
PINK = "#EF87B4"
GREEN = "#C1D56D"
INK = "#252228"
FONT_FALLBACK = "Microsoft YaHei UI"


def select_font(window):
    installed = set(tkfont.families(window))
    return next((name for name in ("Noto Sans SC", "Source Han Sans SC", "思源黑体 CN", FONT_FALLBACK)
                 if name in installed), "TkDefaultFont")


COLOR_SCHEMES = {
    "Light": {
        "bg_root": "#FFF2F8", "bg_card": "#FFFFFF", "bg_input": "#F9FAFF",
        "bg_sidebar": "#FFFCFE", "bg_ghost": "#F9EEF5", "border": "#DDE2F3",
        "text_primary": "#10163E", "text_heading": "#080D32", "text_secondary": "#5D6998",
        "text_muted": "#626D8E", "text_button": "#253567", "text_button_dim": "#5D6998",
        "accent": "#226DD4", "accent_hover": "#2169CB", "accent_bg": "#EAF3FF",
        "accent_text": "#0063DB", "on_accent": "#FFFFFF", "ghost_hover": "#FCEFF7",
        "history_bg": "#F7F9FF", "placeholder": "#9CA7C9",
        "pink_bg": "#FFF0F7", "pink_text": "#C91B76", "pink_border": "#FFD4E9",
        "download": "#D52A87", "download_hover": "#C61B78", "on_download": "#FFFFFF",
        "selection": "#F454A4",
        "success": GREEN, "success_hover": "#D0E188", "success_bg": "#EAF8DE",
        "success_text": "#257014", "on_success": INK,
        "warning": "#8A5A16", "error": "#AC344D",
        "disabled_bg": "#EEE7EC", "disabled_text": "#877A83",
        "progress_track": "#EDF1FC", "art_line": "#FFD5EA",
    },
    "Dark": {
        "bg_root": "#201D23", "bg_card": "#2D2930", "bg_input": "#252228",
        "bg_sidebar": "#252228", "bg_ghost": "#37313A", "border": "#514752",
        "text_primary": "#F9F4F7", "text_heading": "#F9F4F7", "text_secondary": "#C1B4BF",
        "text_muted": "#AA9DA7", "text_button": "#F9F4F7", "text_button_dim": "#C1B4BF",
        "accent": "#226DD4", "accent_hover": "#2169CB", "accent_bg": "#203C46",
        "accent_text": "#73DAF6", "on_accent": "#FFFFFF", "ghost_hover": "#3B343E",
        "history_bg": "#332D35", "placeholder": "#AA9DA7",
        "pink_bg": "#482D3A", "pink_text": "#F3B2CD",
        "pink_border": "#684255", "download": "#D52A87", "download_hover": "#C61B78", "on_download": "#FFFFFF",
        "selection": "#F454A4",
        "success": GREEN, "success_hover": "#D0E188", "success_bg": "#343D28",
        "success_text": "#D2E79A", "on_success": INK,
        "warning": "#F0CC7C", "error": "#FFACC0",
        "disabled_bg": "#403741", "disabled_text": "#AD9EAA",
        "progress_track": "#403741", "art_line": "#61535F",
    },
}
