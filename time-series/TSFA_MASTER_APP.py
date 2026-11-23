
"""
TSFA MASTER APP
Unified navigation for TSFA V1.1 - V1.5.
Original version files are loaded in memory and are never modified.
"""

from __future__ import annotations

import ast
import os
import sys
import traceback
from pathlib import Path

import streamlit as st


BASE_DIR = Path(__file__).resolve().parent
os.chdir(BASE_DIR)

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


VERSION_SOURCES = {
    "TSFA V1.1": "TSFA_Dual_Market_V1_1.py",
    "TSFA V1.2": "TSFA_Dual_Market_V1_2.py",
    "TSFA V1.3": "TSFA_Dual_Market_V1_3.py",
    "TSFA V1.4": "TSFA_Dual_Market_V1_4.py",
    "TSFA V1.5": "V1_5_TEMP_BACKUP/TSFA_Dual_Market_V1_5.py",
}


def check_sources():
    results = {}

    for version, relative_path in VERSION_SOURCES.items():
        path = BASE_DIR / relative_path
        results[version] = path

    missing = [
        f"{version}: {path}"
        for version, path in results.items()
        if not path.is_file()
    ]

    if missing:
        st.error("Ada source versi TSFA yang tidak ditemukan:")
        for item in missing:
            st.write(item)
        st.stop()

    return results


def remove_page_config(tree):
    """Remove standalone top-level st.set_page_config calls in memory."""
    class PageConfigRemover(ast.NodeTransformer):
        def visit_Module(self, node):
            kept = []

            for statement in node.body:
                target = (
                    isinstance(statement, ast.Expr)
                    and isinstance(statement.value, ast.Call)
                    and isinstance(statement.value.func, ast.Attribute)
                    and statement.value.func.attr == "set_page_config"
                    and isinstance(statement.value.func.value, ast.Name)
                    and statement.value.func.value.id == "st"
                )

                if not target:
                    kept.append(statement)

            node.body = kept
            return node

    tree = PageConfigRemover().visit(tree)
    ast.fix_missing_locations(tree)
    return tree


def run_version(version, source_path):
    try:
        source = source_path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(source_path))
        tree = remove_page_config(tree)

        compiled = compile(tree, str(source_path), "exec")

        # V1.5 lives in a subfolder, but its engine modules live in BASE_DIR.
        # Give it a virtual root-level __file__ so its BASE_DIR resolves correctly.
        virtual_file = BASE_DIR / source_path.name

        namespace = {
            "__name__": "__main__",
            "__file__": str(virtual_file),
            "__package__": None,
            "__builtins__": __builtins__,
        }

        exec(compiled, namespace, namespace)

    except Exception as exc:
        st.error(f"{version} gagal dijalankan.")
        st.exception(exc)
        with st.expander("Detail teknis"):
            st.code(traceback.format_exc())


st.set_page_config(
    page_title="TSFA Dual Market",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("TSFA Dual Market")
st.caption("Unified application — V1.1 sampai V1.5")

sources = check_sources()

with st.sidebar:
    st.header("TSFA Version")
    selected_version = st.radio(
        "Pilih versi aplikasi",
        list(VERSION_SOURCES.keys()),
        index=4,
    )

    st.divider()
    st.caption("Source versi asli tidak dimodifikasi.")
    st.caption("V1.4 dan V1.5 tetap berjalan secara lokal.")

st.subheader(selected_version)

selected_path = sources[selected_version]
run_version(selected_version, selected_path)
