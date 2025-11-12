#!/usr/bin/env python3
import sys, os, tempfile, uuid
from dataclasses import dataclass
from typing import List, Tuple
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget,
    QLabel, QFileDialog, QComboBox, QDoubleSpinBox, QSpinBox, QLineEdit,
    QProgressBar, QMessageBox, QGroupBox, QFormLayout, QSplitter, QScrollArea,
    QListWidgetItem
)
from PyQt6.QtGui import QPixmap, QImage, QIcon
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyPDF2 import PdfReader
import fitz
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm

POINTS_PER_CM = 28.346456692913385

@dataclass
class PDFItem:
    path: str
    num_pages: int

def cm_to_points(value_cm: float) -> float:
    return value_cm * POINTS_PER_CM

def render_pdf_page_to_qimage(pdf_path: str, page_number: int, dpi: int = 80) -> QImage:
    doc = fitz.open(pdf_path)
    try:
        page = doc.load_page(page_number)
        mat = fitz.Matrix(dpi / 72.0, dpi / 72.0)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img_bytes = pix.tobytes("png")
        return QImage.fromData(img_bytes)
    finally:
        doc.close()

# ================== Worker PDF ==================
class Worker(QThread):
    progress = pyqtSignal(int)
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, files: List[PDFItem], output_folder: str, page_size_pts: Tuple[float, float],
                 orientation: str, pages_per_sheet: int, spacing_cm: float, page_order_dict=None, dpi: int = 150):
        super().__init__()
        self.files = files
        self.output_folder = output_folder
        self.page_size_pts = page_size_pts
        self.orientation = orientation
        self.pages_per_sheet = pages_per_sheet
        self.page_order_dict = page_order_dict or {}
        self.spacing_cm = spacing_cm
        self.dpi = dpi

    def run(self):
        try:
            total_files = len(self.files)
            if total_files == 0:
                self.error.emit("No hay archivos para procesar.")
                return
            for idx_file, item in enumerate(self.files):
                base = os.path.splitext(os.path.basename(item.path))[0]
                out_path = os.path.join(self.output_folder, f"{base}_editado.pdf")
                order = self.page_order_dict.get(idx_file, None)
                self._generate_pdf(item.path, out_path, order)
                self.progress.emit(int(((idx_file + 1) / total_files) * 100))
            self.finished.emit(self.output_folder)
        except Exception as e:
            self.error.emit(str(e))

    def _generate_pdf(self, input_pdf: str, output_pdf: str, page_order=None):
        reader = PdfReader(input_pdf)
        width_pt, height_pt = self.page_size_pts
        if self.orientation == "Horizontal":
            page_w, page_h = max(width_pt, height_pt), min(width_pt, height_pt)
        else:
            page_w, page_h = min(width_pt, height_pt), max(width_pt, height_pt)

        c = canvas.Canvas(output_pdf, pagesize=(page_w, page_h))
        positions = self._layout_positions(page_w, page_h, self.pages_per_sheet, self.spacing_cm)
        total_pages = len(reader.pages)

        if page_order:
            page_indices = page_order
        else:
            page_indices = list(range(total_pages))

        idx = 0
        while idx < total_pages:
            for slot in range(self.pages_per_sheet):
                if idx >= total_pages:
                    break
                temp_img = os.path.join(tempfile.gettempdir(), f"{uuid.uuid4()}.png")
                self._save_page_as_png(input_pdf, page_indices[idx], temp_img)
                x, y, w, h = positions[slot]
                c.drawImage(temp_img, x, y, width=w, height=h, preserveAspectRatio=True)
                os.remove(temp_img)
                idx += 1
            c.showPage()
        c.save()

    def _save_page_as_png(self, pdf_path: str, page_no: int, out_path: str):
        doc = fitz.open(pdf_path)
        page = doc.load_page(page_no)
        mat = fitz.Matrix(self.dpi / 72.0, self.dpi / 72.0)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        pix.save(out_path)
        doc.close()

    def _layout_positions(self, page_w: float, page_h: float, per_sheet: int, spacing_cm: float):
        s = cm_to_points(spacing_cm)
        if per_sheet == 2:
            w = (page_w - 3*s)/2
            h = page_h - 2*s
            return [(s, s, w, h), (2*s+w, s, w, h)]
        if per_sheet == 4:
            w = (page_w - 3*s)/2
            h = (page_h - 3*s)/2
            return [(s, s, w, h),(2*s+w, s, w, h),(s,2*s+h,w,h),(2*s+w,2*s+h,w,h)]
        if per_sheet == 8:
            w = (page_w - 5*s)/4
            h = (page_h - 3*s)/2
            return [(s, s, w, h),(2*s+w, s, w, h),(3*s+2*w, s, w, h),(4*s+3*w, s, w, h),
                    (s, 2*s+h, w, h),(2*s+w, 2*s+h, w, h),(3*s+2*w, 2*s+h, w, h),(4*s+3*w, 2*s+h, w, h)]
        return [(s, s, page_w-2*s, page_h-2*s)]

# ================== Worker miniaturas ==================
class ThumbnailWorker(QThread):
    thumbnail_ready = pyqtSignal(int, QIcon)

    def __init__(self, pdf_path: str, total_pages: int):
        super().__init__()
        self.pdf_path = pdf_path
        self.total_pages = total_pages

    def run(self):
        for i in range(self.total_pages):
            try:
                img = render_pdf_page_to_qimage(self.pdf_path, i, dpi=50)
                pix = QPixmap.fromImage(img).scaledToWidth(80, Qt.TransformationMode.SmoothTransformation)
                icon = QIcon(pix)
                self.thumbnail_ready.emit(i, icon)
            except Exception as e:
                print(f"No se pudo generar miniatura de página {i+1}: {e}")

# ================== Preview Area ==================
class PreviewArea(QWidget):
    def __init__(self):
        super().__init__()
        self.layout = QVBoxLayout(self)
        self.layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.layout.setSpacing(12)
        self.layout.setContentsMargins(10, 10, 10, 10)

    def clear(self):
        while self.layout.count():
            item = self.layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def add_page(self, pixmap: QPixmap):
        label = QLabel()
        label.setPixmap(pixmap)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("border: 1px solid #333; background: #1a1a1a;")
        self.layout.addWidget(label)

# ================== Main GUI ==================
class EditorDePDF(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("🗂️ Editor de PDF — por Jose Livia")
        self.resize(1250, 720)
        self.setStyleSheet(self.estilo_visual())
        self.files: List[PDFItem] = []
        self.worker = None
        self.page_order_dict = {}

        # left
        self.list_widget = QListWidget()
        self.btn_add = QPushButton("Cargar PDF")
        self.btn_remove = QPushButton("Quitar seleccionado")
        left_layout = QVBoxLayout()
        left_layout.addWidget(self.list_widget)
        left_layout.addWidget(self.btn_add)
        left_layout.addWidget(self.btn_remove)

        # lista de páginas
        self.pages_list = QListWidget()
        self.pages_list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.pages_list.setFixedWidth(180)
        self.pages_list.model().rowsMoved.connect(self.update_page_order)
        self.page_order: List[int] = []

        left_h_layout = QHBoxLayout()
        left_h_layout.addLayout(left_layout)
        left_h_layout.addWidget(self.pages_list)
        left_group = QGroupBox("Archivos y Páginas")
        left_group.setLayout(left_h_layout)

        # center (scrollable preview)
        self.preview_area = PreviewArea()
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(self.preview_area)
        self.scroll.setStyleSheet("background:#121212; border:1px solid #333;")
        center_layout = QVBoxLayout(); center_layout.addWidget(self.scroll)
        center_group = QGroupBox("Previsualización completa"); center_group.setLayout(center_layout)

        # right
        form = QFormLayout()
        self.size_combo = QComboBox(); self.size_combo.addItems(["A4 (21x29.7cm)","Carta (21.6x27.9cm)","Personalizado"])
        self.custom_w = QDoubleSpinBox(); self.custom_h = QDoubleSpinBox()
        for s in (self.custom_w, self.custom_h):
            s.setRange(1,1000); s.setValue(21.0); s.setSuffix(" cm")
        self.custom_h.setValue(29.7)

        self.orientation_combo = QComboBox(); self.orientation_combo.addItems(["Vertical","Horizontal"])
        self.pages_per_sheet_combo = QComboBox(); self.pages_per_sheet_combo.addItems(["1","2","4","8","Personalizado"])
        self.pages_custom_spin = QSpinBox()
        self.pages_custom_spin.setRange(1,100)
        self.pages_custom_spin.setValue(1)
        self.pages_custom_spin.setSuffix(" pág.")
        self.pages_custom_spin.hide()
        self.pages_per_sheet_combo.currentTextChanged.connect(self.check_pages_custom)

        self.spacing_spin = QDoubleSpinBox(); self.spacing_spin.setRange(0,5); self.spacing_spin.setValue(0.17); self.spacing_spin.setSuffix(" cm")

        form.addRow("Tamaño:", self.size_combo)
        form.addRow("Ancho:", self.custom_w)
        form.addRow("Alto:", self.custom_h)
        form.addRow("Orientación:", self.orientation_combo)
        form.addRow("Páginas por hoja:", self.pages_per_sheet_combo)
        form.addRow("Personalizado:", self.pages_custom_spin)
        form.addRow("Separación:", self.spacing_spin)

        self.select_output_button = QPushButton("Seleccionar carpeta de salida")
        self.output_line = QLineEdit()
        self.btn_preview = QPushButton("Cargar previsualización")
        self.generate_button = QPushButton("Generar PDF")
        self.progress_bar = QProgressBar()
        right_layout = QVBoxLayout()
        right_layout.addLayout(form)
        right_layout.addWidget(self.select_output_button)
        right_layout.addWidget(self.output_line)
        right_layout.addWidget(self.btn_preview)
        right_layout.addWidget(self.generate_button)
        right_layout.addWidget(self.progress_bar)
        right_layout.addStretch()
        right_group = QGroupBox("Configuración y acciones")
        right_group.setLayout(right_layout)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_group); splitter.addWidget(center_group); splitter.addWidget(right_group)
        splitter.setSizes([320,600,320])
        main = QHBoxLayout(); main.addWidget(splitter)
        self.setLayout(main)

        self.btn_add.clicked.connect(self.load_files)
        self.btn_remove.clicked.connect(self.remove_selected)
        self.list_widget.currentRowChanged.connect(self.fill_pages_list)
        self.btn_preview.clicked.connect(self.generate_preview)
        self.select_output_button.clicked.connect(self.choose_output_folder)
        self.generate_button.clicked.connect(self.on_generate_clicked)

    # ======== Archivos y páginas ========
    def load_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self,"Seleccionar PDF(s)",os.getcwd(),"PDF Files (*.pdf)")
        for p in paths:
            try:
                num = len(PdfReader(p).pages)
                self.files.append(PDFItem(p, num))
                self.list_widget.addItem(f"{os.path.basename(p)} — {num} pág.")
            except Exception as e:
                QMessageBox.warning(self,"Error",f"No se pudo abrir {p}\n{e}")

    def remove_selected(self):
        r = self.list_widget.currentRow()
        if r>=0:
            self.list_widget.takeItem(r)
            self.files.pop(r)
            self.pages_list.clear()
            self.preview_area.clear()
            if r in self.page_order_dict: del self.page_order_dict[r]

    def fill_pages_list(self, idx_file: int):
        self.pages_list.clear()
        if idx_file < 0 or idx_file >= len(self.files):
            return
        self.page_order = list(range(self.files[idx_file].num_pages))
        self.page_order_dict[idx_file] = self.page_order.copy()

        # Crear items de texto primero
        for i in range(self.files[idx_file].num_pages):
            item = QListWidgetItem(f"Página {i+1}")
            self.pages_list.addItem(item)

        # Worker de miniaturas
        self.thumb_worker = ThumbnailWorker(self.files[idx_file].path, self.files[idx_file].num_pages)
        self.thumb_worker.thumbnail_ready.connect(self.update_thumbnail_icon)
        self.thumb_worker.start()

    def update_thumbnail_icon(self, index: int, icon: QIcon):
        item = self.pages_list.item(index)
        if item:
            item.setIcon(icon)

    def update_page_order(self):
        self.page_order = [self.pages_list.row(self.pages_list.item(i)) for i in range(self.pages_list.count())]
        idx_file = self.list_widget.currentRow()
        if idx_file >= 0:
            self.page_order_dict[idx_file] = self.page_order.copy()

    def check_pages_custom(self, text):
        if text == "Personalizado":
            self.pages_custom_spin.show()
        else:
            self.pages_custom_spin.hide()

    # ======== Previsualización ========
    def generate_preview(self):
        if not self.files:
            QMessageBox.information(self, "Info", "Cargá un PDF primero."); return
        idx = self.list_widget.currentRow()
        if idx < 0: idx = 0
        item = self.files[idx]
        tmp_out = os.path.join(tempfile.gettempdir(), f"preview_{uuid.uuid4()}.pdf")

        size = self._page_size()
        orientation = self.orientation_combo.currentText()
        pages_per_sheet = self.pages_custom_spin.value() if self.pages_per_sheet_combo.currentText()=="Personalizado" else int(self.pages_per_sheet_combo.currentText())
        spacing = float(self.spacing_spin.value())

        # Obtener orden actual de la lista de páginas
        page_order = [self.pages_list.row(self.pages_list.item(i)) for i in range(self.pages_list.count())]

        worker = Worker([item], tempfile.gettempdir(), size, orientation, pages_per_sheet, spacing, page_order_dict={0: page_order})
        worker._generate_pdf(item.path, tmp_out, page_order=page_order)

        self.preview_area.clear()
        try:
            doc = fitz.open(tmp_out)
            for page_number in range(len(doc)):
                img = render_pdf_page_to_qimage(tmp_out, page_number, dpi=80)
                pix = QPixmap.fromImage(img)
                scaled = pix.scaledToWidth(500, Qt.TransformationMode.SmoothTransformation)
                self.preview_area.add_page(scaled)
            doc.close()
        except Exception as e:
            self.preview_area.clear()
            lbl = QLabel(f"Error al generar previsualización: {e}")
            lbl.setStyleSheet("color:red;")
            self.preview_area.layout.addWidget(lbl)
        finally:
            if os.path.exists(tmp_out): os.remove(tmp_out)

    # ======== PDF final ========
    def choose_output_folder(self):
        folder = QFileDialog.getExistingDirectory(self,"Seleccionar carpeta",os.getcwd())
        if folder: self.output_line.setText(folder)

    def on_generate_clicked(self):
        if not self.files:
            QMessageBox.information(self,"Info","Cargá un PDF primero."); return
        out = self.output_line.text().strip()
        if not out:
            QMessageBox.information(self,"Info","Seleccioná una carpeta de salida."); return
        size = self._page_size()
        pages_per_sheet = self.pages_custom_spin.value() if self.pages_per_sheet_combo.currentText()=="Personalizado" else int(self.pages_per_sheet_combo.currentText())
        w = Worker(self.files, out, size,
                   self.orientation_combo.currentText(),
                   pages_per_sheet,
                   float(self.spacing_spin.value()),
                   page_order_dict=self.page_order_dict)
        w.progress.connect(self.progress_bar.setValue)
        w.finished.connect(lambda f: QMessageBox.information(self,"Listo",f"Guardado en {f}"))
        w.error.connect(lambda e: QMessageBox.warning(self,"Error",e))
        w.start()

    # ======== Helpers ========
    def _page_size(self):
        c = self.size_combo.currentText()
        if c.startswith("A4"): return (cm_to_points(21.0), cm_to_points(29.7))
        if c.startswith("Carta"): return (cm_to_points(21.59), cm_to_points(27.94))
        return (cm_to_points(self.custom_w.value()), cm_to_points(self.custom_h.value()))

    def estilo_visual(self):
        return """
        QWidget{background:#121212;color:#f0f0f0;}
        QGroupBox{border:1px solid #2a2a2a;border-radius:8px;padding:8px;}
        QPushButton{background:#0078d7;color:white;border-radius:6px;padding:6px;}
        QPushButton:hover{background:#1491ff;}
        QListWidget{background:#1e1e1e;border:1px solid #333;}
        QLineEdit,QDoubleSpinBox,QComboBox,QSpinBox{background:#1b1b1b;color:#f0f0f0;}
        QProgressBar{background:#222;color:#f0f0f0;}
        """

def main():
    app = QApplication(sys.argv)
    w = EditorDePDF(); w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
