"""Build the six practice reports from the implemented code and test evidence."""
import json
import sys
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "Практические" / "Отчёты"
QA = ROOT / "artifacts/practice-analysis"
OUT.mkdir(parents=True, exist_ok=True)
evidence = json.loads((QA / "verification.json").read_text(encoding="utf-8"))
integration = json.loads((QA / "workspace-verification.json").read_text(encoding="utf-8"))
http_total = evidence["passed"] + integration["passed"]
newman = json.loads((QA / "newman.json").read_text(encoding="utf-8"))["run"]["stats"]
FONT = Path("C:/Windows/Fonts/arial.ttf")


def diagram(filename, architecture=False):
    image = Image.new("RGB", (1740, 960), "white")
    draw = ImageDraw.Draw(image)
    regular = ImageFont.truetype(str(FONT), 29)
    small = ImageFont.truetype(str(FONT), 25)
    bold = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 32)

    def box(x, y, w, title, lines, h=350):
        draw.rounded_rectangle((x, y, x+w, y+h), radius=16, fill="#f7f9fc", outline="#66798b", width=3)
        draw.rounded_rectangle((x, y, x+w, y+64), radius=16, fill="#dce8f1")
        draw.text((x+22, y+16), title, font=bold, fill="#142f46")
        for i, line in enumerate(lines):
            draw.text((x+22, y+88+i*45), line, font=regular, fill="#172b3a")

    def arrow(start, end, label, pos):
        draw.line((*start, *end), fill="#445e75", width=4)
        x,y = end
        direction = 1 if end[0] >= start[0] else -1
        draw.polygon([(x,y),(x-17*direction,y-11),(x-17*direction,y+11)], fill="#445e75")
        draw.text(pos, label, font=small, fill="#445e75")

    if architecture:
        box(35, 110, 470, "Tauri 2 и Rust", ["Окно и жизненный цикл", "Запуск и остановка sidecar", "IPC service_request", "Токен локального сервиса"])
        box(635, 110, 470, "FastAPI sidecar", ["Router → Service → ORM", "SQLAlchemy и SQLite", "Прогноз на месяц", "CatBoost и Ridge"])
        box(1235, 110, 470, "React и WebView", ["Ввод, отчёты и справочники", "Фильтры и страницы", "Формы CRUD", "Графики и сценарии"])
        arrow((505,280),(635,280),"spawn / kill",(510,225))
        arrow((1235,365),(1105,365),"IPC → HTTP",(1108,410))
        box(460, 610, 820, "SQLite в каталоге данных приложения", ["control_points  →  indicators  →  measurements", "model_months — погодные и прочие признаки", "source_datasets — импортированные исходные таблицы"], h=280)
        draw.line((865,460,865,610), fill="#445e75", width=4)
        draw.text((910,520), "Чтение и транзакции", font=small, fill="#445e75")
    else:
        box(30, 75, 490, "control_points", ["PK  id", "UQ  code", "name, description", "active, created_at"])
        box(625, 75, 490, "indicators", ["PK  id     FK  point_id", "UQ  code", "name, unit, medium", "min_value, max_value, norm", "created_at"])
        box(1220, 75, 490, "measurements", ["PK  id     FK  indicator_id", "month, value, comment", "created_at", "UQ (month, indicator_id)"])
        arrow((520,255),(625,255),"1 : N",(535,203))
        arrow((1115,255),(1220,255),"1 : N",(1130,203))
        box(110, 580, 700, "model_months", ["PK  month", "values JSON — вспомогательные признаки"], h=230)
        box(930, 580, 700, "source_datasets", ["PK  name", "rows JSON — архив исходных таблиц"], h=230)
        draw.text((110,865), "schema_migrations(version PK) хранит применённые версии схемы и импорта", font=regular, fill="#334b60")
    image.save(OUT / filename)


diagram("ER-диаграмма.png")
diagram("Архитектура.png", True)


def report(number, title, opening):
    doc = Document()
    section = doc.sections[0]
    section.page_width, section.page_height = Inches(8.5), Inches(11)
    section.top_margin = section.bottom_margin = Inches(.7)
    section.left_margin = section.right_margin = Inches(.75)
    for name in ("Normal", "Title", "Subtitle", "Heading 1", "Heading 2", "Heading 3"):
        style = doc.styles[name]
        style.font.name = "Times New Roman"
        style.font.color.rgb = RGBColor(0,0,0)
        style.paragraph_format.space_after = Pt(6)
        rfonts = style.element.get_or_add_rPr().find(qn("w:rFonts"))
        if rfonts is not None:
            for attribute in ("asciiTheme", "hAnsiTheme", "cstheme", "eastAsiaTheme"):
                rfonts.attrib.pop(qn("w:" + attribute), None)
    for border in list(doc.styles.element.iter(qn("w:pBdr"))):
        border.getparent().remove(border)
    normal = doc.styles["Normal"]
    normal.font.size = Pt(11.5)
    normal.paragraph_format.line_spacing = 1.12
    doc.styles["Title"].font.size = Pt(22)
    doc.styles["Heading 1"].font.size = Pt(16)
    doc.styles["Heading 2"].font.size = Pt(13)
    doc.core_properties.title = f"Практическая работа {number}. {title}"
    doc.core_properties.subject = "Клиент-серверное приложение Агроэкосистема"
    doc.core_properties.author = ""
    doc.add_paragraph(f"Практическая работа {number}", "Title")
    doc.add_paragraph(title, "Subtitle")
    p(doc, "Проект Агроэкосистема · 1 ноября 2026 года")
    p(doc, opening)
    return doc


def p(doc, text):
    para = doc.add_paragraph(text)
    para.paragraph_format.widow_control = True
    return para


def h(doc, text, level=1):
    return doc.add_heading(text, level)


def page(doc, title):
    doc.add_page_break()
    h(doc, title)


def table(doc, headers, rows, widths=None):
    t = doc.add_table(rows=1, cols=len(headers))
    t.autofit = False
    widths = widths or [7/len(headers)]*len(headers)
    for col, width in zip(t.columns, widths):
        col.width = Inches(width)
    for row_index, row_values in enumerate([headers, *rows]):
        cells = t.rows[0].cells if row_index == 0 else t.add_row().cells
        for i, (cell, value) in enumerate(zip(cells, row_values)):
            cell.width = Inches(widths[i])
            cell.text = str(value)
            tcpr = cell._tc.get_or_add_tcPr()
            margins = OxmlElement("w:tcMar")
            for edge in ("top", "left", "bottom", "right"):
                el = OxmlElement("w:" + edge); el.set(qn("w:w"), "85"); el.set(qn("w:type"), "dxa"); margins.append(el)
            tcpr.append(margins)
            borders = OxmlElement("w:tcBorders")
            for edge in ("top", "left", "bottom", "right"):
                el = OxmlElement("w:" + edge); el.set(qn("w:val"), "single"); el.set(qn("w:sz"), "4"); el.set(qn("w:color"), "D9D9D9"); borders.append(el)
            tcpr.append(borders)
            if row_index == 0:
                shade = OxmlElement("w:shd"); shade.set(qn("w:fill"), "E5EDF4"); tcpr.append(shade)
            for para in cell.paragraphs:
                para.paragraph_format.space_after = Pt(2)
                para.paragraph_format.line_spacing = 1.02
                for run in para.runs:
                    run.font.size = Pt(10.5); run.bold = row_index == 0
        trpr = t.rows[row_index]._tr.get_or_add_trPr()
        keep = OxmlElement("w:cantSplit"); trpr.append(keep)
        if row_index == 0:
            repeat = OxmlElement("w:tblHeader"); trpr.append(repeat)
    doc.add_paragraph().paragraph_format.space_after = Pt(0)
    return t


def code(doc, text):
    for line in text.splitlines():
        paragraph = doc.add_paragraph()
        paragraph.paragraph_format.space_after = Pt(0)
        paragraph.paragraph_format.line_spacing = 1
        run = paragraph.add_run(line)
        run.font.name = "Consolas"; run.font.size = Pt(9)
    doc.add_paragraph().paragraph_format.space_after = Pt(0)


def picture(doc, filename, caption, width=7):
    paragraph = doc.add_paragraph()
    paragraph.add_run().add_picture(str(OUT / filename), width=Inches(width))
    paragraph.paragraph_format.space_after = Pt(3)
    paragraph.paragraph_format.keep_with_next = True
    caption_p = p(doc, caption)
    caption_p.paragraph_format.space_after = Pt(10)
    for run in caption_p.runs: run.font.size = Pt(10)


def save(doc, number):
    if "--only" in sys.argv:
        selected = sys.argv[sys.argv.index("--only") + 1].split(",")
        if str(number) not in selected:
            return
    path = OUT / f"Практика_{number:02d}.docx"
    def counted(value, forms):
        form = forms[2] if 11 <= value % 100 <= 14 else forms[0] if value % 10 == 1 else forms[1] if 2 <= value % 10 <= 4 else forms[2]
        return f"{value} {form}"
    request_count = counted(newman['requests']['total'], ("запрос", "запроса", "запросов"))
    assertion_count = counted(newman['assertions']['total'], ("утверждение", "утверждения", "утверждений"))
    postman_text = f"{request_count} и {assertion_count}"
    paragraphs = list(doc.paragraphs) + [paragraph for tab in doc.tables for row in tab.rows for cell in row.cells for paragraph in cell.paragraphs]
    for paragraph in paragraphs:
        for run in paragraph.runs:
            revised = run.text.replace("37 запросов и 49 утверждений", postman_text)
            revised = revised.replace(f"{newman['requests']['total']} запросов", request_count)
            revised = revised.replace(f"{newman['assertions']['total']} утверждений", assertion_count)
            if revised != run.text:
                run.text = revised
    doc.save(path)
    print(path.name, len(doc.paragraphs), "paragraphs")


# Practice 1
d = report(1, "Анализ предметной области и требования к системе", "Разработано описание клиент-серверного приложения для учёта измерений и прогнозирования основных загрязняющих веществ в сточных водах. Требования согласованы с месячным горизонтом существующих ML-моделей и с локальной архитектурой Tauri и FastAPI.")
h(d, "Назначение и предметная область")
p(d, "Объект автоматизации — поля фильтрации промышленного предприятия с пятью последовательно расположенными контрольными точками. Лабораторные измерения позволяют оценивать изменение состава сточных вод при прохождении очистки. Отдельно учитываются донные отложения, общий объём стока и месячный расход препарата.")
p(d, "Система объединяет разрозненные таблицы измерений, хранит их в SQLite и предоставляет прогноз на следующий месяц. Результаты используются инженером для сравнения сценариев и анализа данных. Расчёт не управляет оборудованием и не заменяет лабораторный контроль.")
h(d, "Пользователи и организационные роли")
table(d, ["Роль", "Задачи"], [("Лаборант", "Вводит и корректирует измерения, проверяет единицы и месяц."), ("Инженер технолог", "Сравнивает контрольные точки, рассчитывает прогноз и сценарии дозировки."), ("Эколог аналитик", "Просматривает историю, статистику и превышения заданных порогов."), ("Ответственный за приложение", "Запускает приложение, переносит данные и сохраняет резервные копии БД.")], [1.7,5.3])
p(d, "Роли описывают рабочие обязанности. В локальной версии нет учётных записей и разграничения прав по ролям; доступ ограничивается рабочим местом и токеном sidecar.")
h(d, "Основные бизнес процессы")
for text in ["1. Лабораторный учёт: выбрать месяц, ввести значения, проверить диапазоны и записать измерения.", "2. Ведение архива: найти запись, исправить ошибку либо удалить измерение после подтверждения.", "3. Анализ очистки: сравнить значения по контрольным точкам и просмотреть историю КТ5.", "4. Прогнозирование: выбрать базовый месяц, задать сценарий и рассчитать следующий месяц.", "5. Подготовка данных: отобрать измерения, получить статистику и выгрузить CSV."]: p(d, text)
page(d, "Функциональные требования")
reqs = [("ФТ01", "Вести справочник контрольных точек.", "Must"), ("ФТ02", "Вести показатели с единицами, средой и диапазоном значений.", "Must"), ("ФТ03", "Записывать измерение показателя за выбранный месяц.", "Must"), ("ФТ04", "Вводить показатели из справочников и показывать готовность 49 входов ML.", "Must"), ("ФТ05", "Читать, изменять и удалять измерения по идентификатору.", "Must"), ("ФТ06", "Искать по русскому тексту и сочетать серверные фильтры.", "Must"), ("ФТ07", "Показывать страницы и сортировать записи на сервере.", "Must"), ("ФТ08", "Импортировать CSV после предварительной проверки.", "Must"), ("ФТ09", "Экспортировать отфильтрованные измерения в CSV.", "Must"), ("ФТ10", "Рассчитывать восемь загрязняющих веществ КТ5 на следующий месяц.", "Must"), ("ФТ11", "Сравнивать сценарии объёма, погоды и расхода препарата.", "Must"), ("ФТ12", "Рассчитывать дозировку с явным указанием достижения цели.", "Must"), ("ФТ13", "Рассчитывать показатели донных отложений.", "Must"), ("ФТ14", "Показывать графики фактических значений и результатов прогноза.", "Must"), ("ФТ15", "Выявлять превышения порогов и формировать агрегаты по показателю и месяцу.", "Must")]
reqs = [(key, text, "Should" if key in {"ФТ11", "ФТ12", "ФТ13", "ФТ15"} else priority) for key, text, priority in reqs]
table(d, ["Код", "Требование", "Приоритет"], reqs, [.65,5.35,1.0])
p(d, "Must — обязательное ядро версии; Should — желательные аналитические функции, также реализованные в проекте.")
h(d, "Признаки модели и дополнительные данные", 2)
p(d, "Используются 40 измерений сточной воды: ХПК, БПК5, аммоний, фосфаты, нитраты, нитриты, жиры и сульфаты для КТ1–КТ5; семь показателей донных отложений КТ5; общий объём стока, м³/мес; общий расход препарата, л/мес. Новые точки и показатели появляются в основной форме ввода, истории и отчётах. Измерения можно записывать частями. Дополнительные показатели не расширяют набор признаков ML.")
page(d, "Нефункциональные требования и границы")
table(d, ["Область", "Требование и способ приёмки"], [("Быстродействие", "Одно активное рабочее место. Страница не более 100 записей. Время ответа CRUD после прогрева — целевое до 2 с; холодный запуск и ML проверяются отдельно."), ("Надёжность", "Транзакции SQLite; уникальность измерения за месяц; запрет удаления зависимых справочников. Данные доступны после повторного запуска."), ("Безопасность", "Сервис слушает loopback. Tauri передаёт случайный Bearer-токен. SQL сортировка ограничена белым списком; внутренние ошибки не раскрывают стек."), ("Восстановление", "Резервная копия — копирование SQLite после закрытия приложения. CSV служит переносом измерений, но не полной резервной копией моделей и служебных данных."), ("Удобство", "Русский интерфейс, подписи единиц, сообщения об ошибках, предварительная проверка CSV и подтверждение удаления в клиенте."), ("Рост нагрузки", "Локальная БД и ограниченные страницы. Многопользовательский сетевой сервер и параллельная работа нескольких рабочих мест в текущую версию не входят.")], [1.6,5.4])
h(d, "Границы системы")
p(d, "В систему входят справочники, месячные измерения, архив, поиск, статистика, импорт и экспорт CSV, диаграммы и три существующих модуля расчёта. SQLite является основным хранилищем. Исходные CSV однократно импортируются при первом запуске; дальнейшие расчёты используют данные БД.")
p(d, "В текущий объём не входят автоматический сбор с датчиков, управление дозирующим оборудованием, интеграция с 1С, сетевые учётные записи, прогноз на 1–3–5 лет и статистически подтверждённый 95-процентный доверительный интервал. Сохранение диаграмм в PNG/PDF и прямой экспорт XLS остаются направлениями развития; CSV можно открыть в Excel.")
h(d, "Уточнения исходного описания", 2)
p(d, "Формулировка про БПК и ХПК заменена на «основные загрязняющие вещества»: модуль воды содержит восемь моделей. Биоплёнка исключена из обязательного ввода из-за неполного покрытия контрольных точек. Горизонт принят равным одному месяцу относительно базового месяца.")
p(d, "Расплывчатые названия производственных цехов не используются как единицы измерения. В обязательной форме явно указаны общий объём сточных вод в м³/мес и расход препарата в л/мес. Детализация потоков требует отдельного согласования состава данных.")
page(d, "Архитектура и приёмка")
picture(d, "Архитектура.png", "Рисунок 1 — Компоненты приложения и хранение данных")
p(d, "Tauri создаёт окно, запускает Python sidecar и завершает его при закрытии приложения. React-формы ввода, отчётов и справочников вызывают Rust-команду service_request; Rust выполняет HTTP-запрос на loopback с токеном. В режиме разработки React обращается к FastAPI напрямую. Порт настольной версии выбирается при запуске, а не закрепляется за 8008.")
table(d, ["Этап", "Результат приёмки"], [("Проектирование", "Описание процессов и требований; ER-диаграмма и ограничения БД."), ("Backend", "SQLAlchemy, схема SQLite, CRUD трёх сущностей, единые ошибки."), ("Работа с наборами", "Пагинация, сортировка, фильтры, русский поиск, три агрегатных метода и отчёт."), ("Интеграция", "Новые точки и показатели используются основными формами и отчётами. Изменения данных сбрасывают старый результат прогноза; схема ML сохраняет 49 признаков."), ("Проверка", f"{http_total} HTTP-проверок; Postman/Newman: 37 запросов и 49 утверждений без ошибок; Vite build и cargo check проходят.")], [1.5,5.5])
h(d, "Вывод", 2)
p(d, "Определены четыре организационные роли, пять процессов, 15 проверяемых функциональных требований и границы локальной версии. Описание приведено в соответствие с реальным набором моделей и архитектурой клиент-серверного приложения.")
save(d, 1)


# Practice 2
d = report(2, "Проектирование базы данных и ER диаграмма", "Спроектировано реляционное хранилище для контрольных точек, показателей и месячных измерений. Модель отделяет справочные данные от результатов лабораторного контроля и сохраняет вспомогательные признаки существующих ML-моделей.")
h(d, "Сущности и связи")
p(d, "Контрольная точка задаёт этап очистки. Показатель описывает измеряемую величину именно в этой точке и среде. Поэтому «ХПК КТ1» и «ХПК КТ5» — разные записи справочника. Измерение связывает показатель с месяцем и числовым значением.")
picture(d, "ER-диаграмма.png", "Рисунок 1 — Физическая ER-диаграмма реализованной SQLite БД")
p(d, "Связь control_points → indicators имеет кратность 1:N; indicators → measurements также 1:N. Внешние ключи обязательны и запрещают удаление родителя при наличии зависимых записей. Один показатель может иметь не более одного измерения за месяц.")
p(d, "Показатели объёма и расхода препарата относятся к среде operation и привязаны к входу системы, КТ1. Поле point_id не дублируется в measurements: точка определяется через показатель.")
page(d, "Словарь данных")
table(d, ["Таблица и поле", "Тип", "Ограничение и смысл"], [("control_points.id", "INTEGER", "Первичный ключ"), ("control_points.code", "VARCHAR(30)", "Уникальный обязательный код"), ("name / description", "VARCHAR", "Название до 160 и описание до 1000 символов"), ("active / created_at", "BOOLEAN / DATETIME", "Активность и время создания"), ("indicators.id / code", "INTEGER / VARCHAR(180)", "PK и уникальный код, совместимый с именем признака"), ("indicators.point_id", "INTEGER", "FK → control_points.id, RESTRICT"), ("name / unit / medium", "VARCHAR", "Название, единица и среда water/sediments/operation"), ("min_value / max_value", "FLOAT", "Нижняя и необязательная верхняя граница"), ("norm", "FLOAT NULL", "Необязательный порог превышения"), ("measurements.id", "INTEGER", "Первичный ключ"), ("indicator_id", "INTEGER", "FK → indicators.id, RESTRICT"), ("month", "VARCHAR(7)", "Месяц YYYY-MM; проверяется API"), ("value", "FLOAT", "Конечное число в диапазоне показателя"), ("comment / created_at", "VARCHAR(1000) / DATETIME", "Примечание и время создания"), ("month + indicator_id", "UNIQUE", "Уникальность месячного измерения"), ("model_months.month / values", "VARCHAR(7) / JSON", "PK месяца и вспомогательные признаки"), ("source_datasets.name / rows", "VARCHAR(100) / JSON", "PK имени и архив импортированной таблицы"), ("schema_migrations.version", "INTEGER", "PK версии схемы или импорта")], [2.25,1.45,3.3])
p(d, "SQLite использует собственные классы хранения; VARCHAR-ограничения длины дополнительно обеспечиваются схемами Pydantic. Диапазоны входных чисел, допустимая среда и корректность месяца проверяются до записи. Внешние ключи включаются для каждого соединения через PRAGMA foreign_keys=ON.")
page(d, "Нормализация и целостность")
h(d, "Нормализация основной модели", 2)
p(d, "Основные сущности приведены к третьей нормальной форме: значения атомарны, справочные атрибуты зависят от собственного ключа, название точки и единица не повторяются в измерениях. Связь измерения с точкой вычисляется JOIN через indicators.")
p(d, "JSON используется только в технических таблицах импорта и совместимости с существующим набором ML-признаков. Эти таблицы не подменяют нормализованный журнал и не используются для пользовательской фильтрации лабораторных записей.")
h(d, "Бизнес ограничения", 2)
table(d, ["Ситуация", "Реакция"], [("Повтор кода точки или показателя", "409 CONFLICT"), ("Повтор измерения за тот же месяц", "409 CONFLICT; CSV-импорт явно обновляет запись"), ("Неизвестный FK", "404 NOT_FOUND до записи"), ("Отрицательное значение при min_value=0", "422 VALIDATION_ERROR"), ("Новая запись в неактивной точке", "422; история остаётся доступной в отчётах"), ("Верхняя граница ниже нижней", "422 VALIDATION_ERROR"), ("Удаление родителя с зависимостями", "409 CONFLICT"), ("Изменение технической схемы обязательного ML-показателя", "409 CONFLICT; разрешено создать отдельный показатель")], [3.4,3.6])
h(d, "Пример ограничения БД", 2)
code(d, "CREATE TABLE measurements (\n  id INTEGER NOT NULL PRIMARY KEY,\n  month VARCHAR(7) NOT NULL,\n  indicator_id INTEGER NOT NULL,\n  value FLOAT NOT NULL,\n  comment VARCHAR(1000) NOT NULL,\n  created_at DATETIME NOT NULL,\n  UNIQUE (month, indicator_id),\n  FOREIGN KEY(indicator_id) REFERENCES indicators(id)\n    ON DELETE RESTRICT\n);")
page(d, "Хранение и проверка модели")
h(d, "Выбор SQLite", 2)
p(d, "SQLite соответствует локальной архитектуре sidecar: отдельный сервер СУБД и установка PostgreSQL пользователю не нужны. SQLAlchemy обеспечивает ORM-модели, сессии и параметризованные запросы. Учебные операции с PK, FK, отношениями, JOIN и транзакциями реализованы на SQLite.")
h(d, "Инициализация и версии", 2)
table(d, ["Версия", "Действие"], [("1", "Создание ORM-таблиц"), ("2", "Создание индексов типовых запросов"), ("3", "Однократный импорт пяти точек, 49 показателей и измерений"), ("4", "Импорт вспомогательной месячной панели и архивов исходных таблиц")], [.8,6.2])
p(d, "Повторный запуск не повторяет импорт и не восстанавливает удалённые пользователем измерения. Основная БД располагается в каталоге данных приложения; при standalone-запуске каталог задаётся --data-dir.")
h(d, "Результаты проверки", 2)
p(d, f"После импорта исходного набора получено {evidence['initial']['points']} контрольных точек, {evidence['initial']['indicators']} показателей и {evidence['initial']['measurements']} измерений за {evidence['initial']['months']} различных месяцев. В тестах подтверждены уникальность, зависимости, защита технической схемы и сохранение данных после повторного открытия приложения.")
code(d, "EXPLAIN QUERY PLAN\nSELECT * FROM measurements\nWHERE indicator_id=1 AND month >= '2024-01'\nORDER BY month;\n-- SEARCH measurements USING INDEX\n-- ix_measurement_indicator_month (indicator_id=? AND month>?)")
p(d, "Полная фактическая DDL-схема сохранена в schema.sql. ER-диаграмма доступна также отдельным PNG для включения в пояснительную записку.")
h(d, "Вывод", 2)
p(d, "Получена схема с двумя связями 1:N, уникальностью месячного измерения и внешними ключами. Реляционная модель поддерживает CRUD и аналитические запросы, а технические таблицы сохраняют совместимость с ML-частью проекта.")
save(d, 2)


# Practice 3
d = report(3, "Настройка backend и подключение ORM", "Настроен backend FastAPI с SQLAlchemy и локальной SQLite БД. Сервис остаётся отдельным Python sidecar, которым управляет Tauri; измерения и необходимые для моделей данные импортируются в БД один раз.")
h(d, "Среда и зависимости")
p(d, "Используется Python 3.12 и виртуальное окружение .venv. Основные зависимости: FastAPI, uvicorn, Pydantic, SQLAlchemy 2.0, pandas, NumPy, CatBoost, scikit-learn и joblib. requirements.txt задаёт ограничения, requirements.lock.txt фиксирует установленное окружение.")
code(d, "python -m venv .venv\n.venv\\Scripts\\python -m pip install -r python_service/requirements.txt\ncd python_service\n..\\.venv\\Scripts\\python -m service --port 8765 --data-dir ../artifacts/dev-data")
h(d, "Структура backend")
table(d, ["Файл", "Ответственность"], [("service/main.py", "Приложение, lifespan, общие обработчики ошибок"), ("service/database.py", "Engine, SessionLocal, версии схемы, get_db"), ("service/models.py", "ORM-классы и индексы"), ("service/catalog_schemas.py", "Pydantic-схемы запроса и ответа"), ("service/catalog_router.py", "HTTP-маршруты журнала, справочников и статистики"), ("service/catalog_service.py", "Правила, транзакции, импорт начальных данных и проекция для ML"), ("service/catalog_repository.py", "SQL-фильтры, JOIN, сортировка и страницы"), ("service/workspace.py", "Общие справочники, форма месяца, история показателя"), ("service/exchange.py", "Проверка, импорт и экспорт CSV"), ("service/predict.py / train.py", "Существующие прогнозы и обучение")], [2.35,4.65])
p(d, "В презентации рассматривается PostgreSQL. Для данного настольного приложения применена SQLite: она разрешена архитектурой проекта и не требует отдельной службы СУБД. ORM и связи реализованы тем же подходом SQLAlchemy.")
page(d, "Подключение и жизненный цикл")
h(d, "Параметры подключения", 2)
p(d, "Без DATABASE_URL файл agroecosystem.sqlite3 создаётся внутри WTP_DATA_DIR. Tauri передаёт путь в пользовательский app-data каталог. В коде отсутствуют пароли БД. .env.example документирует переменную; .env автоматически не загружается.")
code(d, "DATABASE_URL = os.environ.get(\n    'DATABASE_URL',\n    f\"sqlite:///{(DATA_DIR / 'agroecosystem.sqlite3').as_posix()}\"\n)\nengine = create_engine(DATABASE_URL,\n    connect_args={'check_same_thread': False, 'timeout': 30})\nSessionLocal = sessionmaker(bind=engine, expire_on_commit=False)")
h(d, "Сессия запроса", 2)
code(d, "def get_db():\n    init_database()\n    with SessionLocal() as session:\n        yield session")
p(d, "FastAPI внедряет сессию через Depends. После запроса сессия закрывается. Сервисный слой выполняет commit при успешной операции и rollback при конфликте ограничения. Сессии не передаются между потоками.")
h(d, "Запуск и остановка", 2)
p(d, "Lifespan FastAPI вызывает init_database до обслуживания запросов. При остановке освобождается пул engine.dispose, что позволяет закрыть SQLite-файл на Windows. В настольной сборке Rust запускает бинарник sidecar, выбирает свободный loopback-порт, передаёт токен и останавливает дочерний процесс при выходе.")
p(d, "Поток данных: React → IPC Tauri → HTTP FastAPI → сервисный слой → SQLAlchemy → SQLite. Схема компонентов приведена в отчёте по первой работе.")
page(d, "Модели и первоначальный импорт")
h(d, "Маппинг таблиц на классы", 2)
code(d, "class ControlPoint(Base):\n    __tablename__ = 'control_points'\n    id: Mapped[int] = mapped_column(primary_key=True)\n    code: Mapped[str] = mapped_column(String(30), unique=True)\n    indicators: Mapped[list['Indicator']] = relationship(\n        back_populates='point')\n\nclass Indicator(Base):\n    __tablename__ = 'indicators'\n    point_id: Mapped[int] = mapped_column(\n        ForeignKey('control_points.id', ondelete='RESTRICT'))")
p(d, "Обе стороны отношений определены через relationship и back_populates. В models.py также объявлены Measurement, ModelMonth и SourceDataset. Модели импортируются до создания таблиц.")
h(d, "Создание схемы", 2)
p(d, "Инициализатор хранит номера выполненных шагов в schema_migrations. Первая версия создаёт таблицы, вторая — индексы, третья — справочники и лабораторные значения, четвёртая — вспомогательные признаки и исходные архивы. Каждый шаг защищён проверкой версии, а импорт выполняется транзакционно.")
p(d, "Операционные поля исходной панели преобразуются в записи measurements. Вспомогательные признаки сохраняются в model_months, исходные таблицы — в source_datasets. В дальнейшем load_model_frame собирает данные из SQLite; CSV-панель не читается при каждом прогнозе.")
h(d, "Сохранение совместимости", 2)
p(d, "Обязательная схема модели содержит 49 полей. Технические коды и диапазоны этих показателей защищены от изменения, чтобы редактирование справочника не нарушало контракт обученных моделей. Дополнительные пользовательские показатели появляются в основных формах и отчётах. Их измерения сохраняются в том же журнале, а в ML передаются только 49 закреплённых признаков.")
page(d, "Проверка backend")
table(d, ["Проверка", "Наблюдаемый результат"], [("GET /health", "200, status=ok, storage=sqlite"), ("Первичная схема", "Созданы три основные и три технические таблицы, включая schema_migrations"), ("Импорт", "5 точек, 49 показателей, 885 измерений"), ("Повторное открытие", "Данные сохраняются, импорт не дублируется"), ("Работа без CSV", "После удаления CSV из тестового каталога работают история и прогноз"), ("Прогноз воды", "В ответе восемь показателей, горизонт — следующий месяц"), ("Сборка клиента", "Vite build и cargo check успешны")], [2.0,5.0])
h(d, "Команды проверки", 2)
code(d, ".venv\\Scripts\\python python_service/tests/contracts.py\n.venv\\Scripts\\python python_service/tests/catalog.py\n.venv\\Scripts\\python python_service/tests/workspace.py\ncd AgroecosystemTauri\nnpm run build\ncargo check --manifest-path src-tauri/Cargo.toml --offline")
p(d, "tests/contracts.py проверяет существующий ML-контракт, 49 полей, запись месяца и авторизацию. tests/catalog.py проверяет новые операции на одноразовой копии данных. Полная SQL-схема и фактический план запроса получены из созданной тестовой БД.")
h(d, "Документация API", 2)
p(d, "При standalone-запуске доступны Swagger UI /docs, ReDoc /redoc и OpenAPI /openapi.json. Для защищённого экземпляра нужен Bearer-токен, созданный Tauri; для ручного учебного тестирования удобен отдельный standalone-процесс на loopback без WTP_API_TOKEN.")
h(d, "Вывод", 2)
p(d, "Подготовлены окружение, конфигурация, ORM-модели и зависимости FastAPI. SQLite стала основным хранилищем, а существующие прогнозы продолжили работать с данными, собранными из БД.")
save(d, 3)


# Practice 4
d = report(4, "Реализация и тестирование CRUD API", "Реализован полный REST CRUD для контрольных точек, показателей и измерений. HTTP-слой отделён от бизнес-правил и запросов ORM. Операции доступны в Swagger/Postman, справочниках и основных React-формах ввода и отчётов.")
h(d, "Сущности и маршруты")
table(d, ["Сущность", "Коллекция", "Элемент"], [("Контрольные точки", "/api/points", "/api/points/{id}"), ("Показатели", "/api/indicators", "/api/indicators/{id}"), ("Измерения", "/api/measurements", "/api/measurements/{id}")], [1.7,2.4,2.9])
table(d, ["Метод", "Операция", "Успех"], [("POST коллекции", "Создание", "201 Created"), ("GET коллекции", "Список с пагинацией", "200 OK"), ("GET элемента", "Чтение по id", "200 OK"), ("PUT элемента", "Полная замена изменяемых полей", "200 OK"), ("PATCH элемента", "Частичное обновление", "200 OK"), ("DELETE элемента", "Удаление", "204 No Content")], [1.6,3.8,1.6])
h(d, "Поток обработки запроса", 2)
p(d, "Router валидирует тело и параметры, сервис проверяет зависимости, диапазоны и ограничения, repository выполняет SQL-запросы. Изменение фиксируется транзакцией. Ответ формируется отдельной схемой; для измерения дополнительно возвращаются название показателя, точка, единица и признак превышения.")
p(d, "В Tauri команда service_request расширена методами PUT, PATCH и DELETE. Список допустимых маршрутов ограничен, абсолютные URL клиент не передаёт. Для 204 клиент возвращает null и не пытается разобрать отсутствующее JSON-тело.")
page(d, "Примеры запросов")
h(d, "Создание связанных записей", 2)
code(d, 'POST /api/points\n{"code":"LAB","name":"Лабораторная точка",\n "description":"Тестовая точка","active":true}\n\nPOST /api/indicators\n{"code":"salt_lab","name":"Соль","unit":"мг/л",\n "medium":"water","point_id":6,\n "min_value":0,"max_value":100,"norm":10}\n\nPOST /api/measurements\n{"month":"2026-10","indicator_id":50,\n "value":20,"comment":"Лабораторный контроль"}')
p(d, "Числа 6 и 50 в примере заменяются идентификаторами из предыдущих ответов. Postman-коллекция сохраняет их в переменные автоматически.")
h(d, "Полная и частичная замена", 2)
code(d, 'PUT /api/measurements/{id}\n{"month":"2026-10","indicator_id":50,\n "value":18,"comment":"Повторное измерение"}\n\nPATCH /api/measurements/{id}\n{"comment":"Проверено инженером"}\n\nDELETE /api/measurements/{id}\nHTTP/1.1 204 No Content')
h(d, "Запись из основной формы", 2)
code(d, 'GET /api/workspace\nPATCH /api/months/2026-10\n{"values":{"50":7.3},\n "catalog_revision":"<revision из ответа workspace>"}\nGET /api/months/2026-10\nGET /api/series/50')
p(d, "Форма передаёт идентификаторы показателей. Сервер проверяет все значения до изменения записей и фиксирует весь набор одной транзакцией. Непереданные значения сохраняются. История и месячный отчёт читают тот же журнал.")
p(d, "PATCH применяет только переданные поля. Явный null для обязательного поля отклоняется; необязательные norm и max_value могут быть очищены значением null. PUT использует полную схему создания и требует обязательные поля.")
page(d, "Валидация и защита целостности")
table(d, ["Правило", "Реализация"], [("Типы и неизвестные поля", "Pydantic, extra=forbid, запрет NaN и Infinity"), ("Строки", "Удаление пробелов по краям и ограничения длины"), ("Месяц", "YYYY-MM, существующий номер месяца, диапазон 1900–2200"), ("Значение", "Проверка min_value и max_value показателя"), ("Уникальность", "UQ code; UQ (month, indicator_id)"), ("Зависимости", "Проверка родителя и внешние ключи SQLite"), ("Удаление", "Связанные справочники и обязательные показатели ML защищены"), ("Безопасность ответа", "Общий текст 500; подробности только в серверном логе")], [2.0,5.0])
h(d, "Примеры ошибок", 2)
code(d, 'HTTP/1.1 409 Conflict\n{"detail":"Запись уже существует",\n "error_code":"CONFLICT"}\n\nHTTP/1.1 404 Not Found\n{"detail":"Запись measurements/999999 не найдена",\n "error_code":"NOT_FOUND"}\n\nHTTP/1.1 422 Unprocessable Entity\n{"detail":"Проверьте параметры запроса",\n "error_code":"VALIDATION_ERROR","errors":[...]}')
p(d, "При конфликте уникальности сервис откатывает сессию. Удаление справочников с зависимостями возвращает 409, а не неуправляемую ошибку внешнего ключа. Для несуществующих идентификаторов GET, PUT, PATCH и DELETE возвращают 404. Технические поля и пороги обязательных ML-показателей защищены от изменения.")
page(d, "Тестирование и результат")
p(d, "Подготовлена коллекция Agroecosystem.postman_collection.json формата Postman 2.1. Для запуска задаётся base_url standalone-сервиса. Коллекция создаёт собственные тестовые записи, сохраняет id, выполняет операции и удаляет созданные зависимости в обратном порядке.")
table(d, ["Проверка", "Результат"], [("Автотесты API", f"{http_total} HTTP-проверок без ошибок"), ("Postman через Newman", f"{newman['requests']['total']} запросов, {newman['assertions']['total']} утверждений, ошибок {newman['assertions']['failed']}"), ("Методы", "POST, GET, PUT, PATCH, DELETE для всех трёх сущностей"), ("Ошибки", "Проверены 404, 409 и 422"), ("Совместимость ML", "Сохранены модели и существующие маршруты прогнозов"), ("Клиент", "Формы создания и изменения, подтверждение удаления, сообщения ошибок")], [2.4,4.6])
h(d, "Воспроизведение проверки", 2)
code(d, 'newman run "Практические/Отчёты/Agroecosystem.postman_collection.json"\n.venv\\Scripts\\python python_service/tests/catalog.py')
p(d, "Тестовую коллекцию следует запускать на отдельной БД разработки. Её код POSTMAN_LAB должен быть свободен перед стартом. При штатном завершении созданные тестовые записи удаляются.")
h(d, "Интерфейс", 2)
p(d, "После создания точки и показателя они появляются в основной форме без изменения кода клиента. Название, единица, среда и диапазон берутся из БД. Запись из формы сразу видна в журнале и отчёте. Переименование обновляет подписи; деактивация убирает точку из нового ввода, сохраняя историю. Изменения сбрасывают прежние результаты прогноза.")
h(d, "Вывод", 2)
p(d, "Для трёх основных сущностей реализованы все шесть REST-операций, отдельные схемы валидации и проверки целостности. Работоспособность подтверждена HTTP-автотестами и выполнением Postman-коллекции через Newman.")
save(d, 4)


# Practice 5
d = report(5, "Пагинация сортировка и обработка ошибок", "Улучшены GET-методы трёх основных сущностей. Список формируется на сервере, поддерживает ограниченный размер страницы и динамическую сортировку по разрешённым ORM-полям. Ошибки приведены к общей форме.")
h(d, "Параметры пагинации")
table(d, ["Параметр", "По умолчанию", "Ограничение"], [("page", "1", "Целое число ≥ 1"), ("per_page", "10", "От 1 до 100"), ("sort_by", "id", "Белый список для выбранной сущности"), ("sort_order", "asc", "asc либо desc")], [1.5,1.6,3.9])
p(d, "Смещение вычисляется как (page − 1) × per_page. Общее число записей считается после применения всех фильтров. Число страниц — ceil(total / per_page). Для пустой выборки total_pages=0; страница за концом набора возвращает пустой items.")
code(d, 'GET /api/measurements?page=2&per_page=5&sort_by=month&sort_order=desc\n\n{"items":[...],"total":885,"page":2,\n "per_page":5,"total_pages":177}')
h(d, "Запрос к БД", 2)
p(d, "Repository строит один набор условий. COUNT выполняется над его подзапросом, затем SQL применяет ORDER BY, OFFSET и LIMIT. Полный список не загружается в Python ради разбиения на страницы. Два SQL-запроса отделяют подсчёт от чтения конкретной страницы.")
code(d, "total = session.scalar(select(func.count())\n    .select_from(statement.subquery()))\nrecords = session.scalars(statement\n    .order_by(sort_column, model.id.asc())\n    .offset((query.page - 1) * query.per_page)\n    .limit(query.per_page)).all()")
page(d, "Безопасная сортировка и общие ошибки")
table(d, ["Сущность", "Разрешённые поля"], [("points", "id, code, name, active, created_at"), ("indicators", "id, code, name, unit, medium, point_id, norm, created_at"), ("measurements", "id, month, value, indicator_id, created_at")], [1.4,5.6])
p(d, "sort_by сначала проверяется по белому списку, затем преобразуется в атрибут ORM-класса. Произвольный SQL не принимается. При равных значениях основного поля id используется как дополнительный ключ, поэтому порядок страниц воспроизводим для неизменного набора данных.")
h(d, "Исключения и обработчики", 2)
table(d, ["Класс или ситуация", "HTTP", "error_code"], [("NotFoundError", "404", "NOT_FOUND"), ("ConflictError", "409", "CONFLICT"), ("BusinessError", "422", "VALIDATION_ERROR"), ("Pydantic / RequestValidationError", "422", "VALIDATION_ERROR"), ("HTTPException", "Заданный статус", "HTTP_<status>"), ("Неверный токен", "401", "UNAUTHORIZED"), ("Непредвиденное исключение", "500", "INTERNAL_ERROR")], [3.5,.9,2.6])
code(d, 'GET /api/points?page=0\nHTTP 422\n{"detail":"Проверьте параметры запроса",\n "error_code":"VALIDATION_ERROR",\n "errors":[{"loc":["query","page"],\n            "msg":"...","type":"greater_than_equal"}]}')
p(d, "Во всех ошибках есть detail и error_code. Для структурной валидации дополнительно возвращается errors с путём поля. Непредвиденные исключения логируются сервером, а клиент получает общее сообщение без стека.")
page(d, "Проверка поведения")
table(d, ["Сценарий", "Ожидаемый и полученный результат"], [("page=1&per_page=2", "Метаданные страницы и не более двух элементов"), ("sort_by=id&sort_order=desc", "Идентификаторы идут по убыванию"), ("page=0", "422"), ("per_page=101", "422"), ("sort_by=malicious", "422, список разрешённых полей"), ("sort_order=bad", "422"), ("GET/DELETE неизвестного id", "404 с единым кодом ошибки"), ("Фильтры плюс пагинация", "total относится к отфильтрованному набору")], [3.3,3.7])
p(d, "Проверки применены ко всем трём сущностям в tests/catalog.py и Postman-коллекции. В интерфейсе для измерений КТ5 в воде получено 133 записи; при 10 строках на странице показано 14 страниц. Переход «Далее» меняет страницу с 1 на 2 с сохранением фильтров.")
h(d, "Клиентское поведение", 2)
p(d, "Изменение фильтра, размера страницы или сортировки сбрасывает номер страницы. Устаревшие ответы игнорируются очисткой React effect. Основная форма передаёт версию справочников; при её изменении сервер отвечает 409 и не записывает значения по устаревшей схеме. Черновики связаны с идентификаторами и временем создания показателя.")
p(d, "В консольной проверке Postman/Newman выполнено 37 запросов и 49 утверждений без ошибок. Сборка React-клиента и проверка Rust-команды обмена прошли успешно.")
h(d, "Вывод", 2)
p(d, "Сервер возвращает ограниченные страницы с метаданными, валидирует сортировку и обрабатывает ошибки единообразно. Интерфейс управляет параметрами запросов, а фильтрация и разбиение набора выполняются в SQL.")
save(d, 5)


# Practice 6
d = report(6, "Серверная фильтрация поиск статистика и отчёт", "Добавлены комбинируемые SQL-фильтры, поиск по тексту, агрегатные запросы и отчёт о превышениях порогов. Анализ выполняется на сервере над данными SQLite и доступен из React-интерфейса.")
h(d, "Фильтры основных сущностей")
table(d, ["Сущность", "Фильтры"], [("Контрольные точки", "code, active, created_from, created_to; поиск по коду, названию и описанию"), ("Показатели", "point_id, medium, unit, has_norm, code; поиск по коду, названию и единице"), ("Измерения", "point_id, indicator_id, medium, month_from, month_to, min_value, max_value, exceeds_norm; поиск по комментарию и связанным названиям")], [1.7,5.3])
p(d, "На каждую основную сущность приходится не менее трёх фильтров. Все фильтры объединяются через AND; поиск по нескольким текстовым полям использует OR. Поиск, сортировка и пагинация работают в одном запросном конвейере.")
code(d, "GET /api/measurements?point_id=5&medium=water\n    &month_from=2025-01&month_to=2025-06\n    &exceeds_norm=true&sort_by=month&sort_order=desc\n    &page=1&per_page=10")
h(d, "Поиск на русском языке", 2)
p(d, "SQLite lower() не обеспечивает нужное сравнение кириллицы. Поэтому для каждого соединения зарегистрирована SQL-функция casefold, использующая Python str.casefold. Поиск выполняется SQL LIKE над casefold полей и строки запроса.")
code(d, "term = query.search.casefold()\n# %, _ и обратная косая черта экранируются.\nstatement = statement.where(or_(\n    func.casefold(Indicator.name).like(pattern, escape='\\\\'),\n    func.casefold(Measurement.comment).like(pattern, escape='\\\\')\n))")
p(d, "Это поиск по подстроке без морфологии и ранжирования. Ввод пользователя передаётся параметрами ORM. Специальные символы LIKE рассматриваются буквально; строка с попыткой SQL-инъекции не расширяет выборку.")
page(d, "JOIN и агрегатные запросы")
h(d, "Фильтрация через связи", 2)
p(d, "Для измерений выполняется JOIN measurements → indicators → control_points. Это позволяет отбирать журнал по среде и точке без дублирования этих атрибутов. Дополнительная загрузка связей joinedload предотвращает отдельный запрос для каждой строки страницы.")
table(d, ["Метод", "Назначение и агрегаты"], [("GET /api/stats/summary", "Число точек и показателей; count измерений и distinct месяцев в выбранном наборе"), ("GET /api/stats/by-indicator", "GROUP BY показатель; count, sum, avg, min, max и число превышений"), ("GET /api/stats/by-month", "GROUP BY месяц; число измерений"), ("GET /api/reports/exceedances", "Топ записей по value/norm; учитываются заданные фильтры")], [2.5,4.5])
p(d, "Суммы и средние рассчитываются отдельно для каждого показателя и его единицы. Суммирование концентраций разных веществ или объёмов с концентрациями не используется как общий KPI. Сумма месячных концентраций носит справочный характер; основной аналитический смысл имеют количество, среднее и диапазон.")
h(d, "Проверяемый пример", 2)
code(d, 'POST /api/measurements\n{"month":"2026-01","indicator_id":50,"value":20}\n\nGET /api/stats/by-indicator?indicator_id=50\n[{"id":50,"name":"Тестовая соль новая","unit":"мг/л",\n  "count":1,"sum":20.0,"avg":20.0,"min":20.0,\n  "max":20.0,"exceedances":1}]')
p(d, "Для порога 10 мг/л отчёт возвращает кратность 2.0. Проверка выполнена на временном показателе и одноразовой БД. Нулевые и отсутствующие пороги исключаются из расчёта кратности, чтобы избежать деления на ноль.")
page(d, "Индексы и план запроса")
table(d, ["Индекс", "Назначение"], [("ix_point_active_name", "Активность и название точки"), ("ix_indicator_point_medium", "Показатели точки по среде"), ("ix_indicator_medium_name", "Среда и название показателя"), ("ix_measurement_indicator_month", "История показателя по диапазону месяцев"), ("ix_measurement_month_value", "Диапазон месяца и значения")], [3.4,3.6])
code(d, "EXPLAIN QUERY PLAN\nSELECT * FROM measurements\nWHERE indicator_id=1 AND month >= '2024-01'\nORDER BY month;\n\nSEARCH measurements USING INDEX\nix_measurement_indicator_month (indicator_id=? AND month>?)")
p(d, "План получен из фактически созданной SQLite БД. Для этого запроса используется индекс, а не полный просмотр таблицы. В SQLite применяется EXPLAIN QUERY PLAN; PostgreSQL EXPLAIN ANALYZE к этой СУБД не относится.")
p(d, "Индексы добавляет версия 2 схемы с проверкой существования. Обычный B-tree не ускоряет произвольный LIKE '%текст%'; для текущего локального объёма выбран поиск по подстроке. Полнотекстовый индекс FTS5 потребует отдельной задачи при росте данных.")
h(d, "Импорт и экспорт отобранного набора", 2)
p(d, "Экспорт применяет те же SQL-фильтры, но выгружает весь отобранный набор, а не одну страницу. Формат UTF-8 с BOM и разделителем ;. Импорт поддерживает предварительную проверку и последующую запись всех строк одной транзакцией. Повтор (month, indicator_code) обновляет существующее значение.")
code(d, "month;indicator_code;value;comment\n2026-10;ХПК_КТ5;198;Лабораторный контроль\n2026-10;БПК5_КТ5;106;Лабораторный контроль")
p(d, "Ограничения: CSV-файл до 2 МБ, импорт до 10000 строк, экспорт до 50000 измерений. При ошибке любой строки записи не вносятся. Повтор одной и той же пары внутри импортируемого файла отклоняется.")
page(d, "Проверка и аналитический результат")
table(d, ["Проверка", "Результат"], [("Три фильтра на сущность", "Проверены точки, показатели и измерения"), ("Русский поиск", "Поиск верхним регистром находит сохранённый русский текст"), ("Объединение с пагинацией", "Общее число учитывает все SQL-условия"), ("Статистика", "Проверены count, sum, avg, min, max и GROUP BY"), ("Отчёт", "Проверена кратность превышения 20 / 10 = 2"), ("Индекс", "EXPLAIN подтверждает ix_measurement_indicator_month"), ("CSV", "Проверены preview, запись, экспорт и откат при ошибке"), ("Postman/Newman", "37 запросов и 49 утверждений без ошибок")], [2.6,4.4])
p(d, "В интерфейсе создана дополнительная КТ6 и показатель кислотности. Основная форма использовала изменённое название, единицу и верхнюю границу 13. В отчёте показаны записи 7.2 за сентябрь и 7.3 за октябрь 2026 года. Показатель отмечен как дополнительный и не включён в 49 признаков ML. История доступна и для неактивных точек.")
p(d, "Статистика пересчитывается по всем выбранным измерениям независимо от текущего номера страницы. Отчёт сортирует превышения по отношению к порогу, поэтому сравниваются безразмерные кратности, а не величины с разными единицами.")
h(d, "Воспроизведение", 2)
code(d, ".venv\\Scripts\\python python_service/tests/catalog.py\n.venv\\Scripts\\python python_service/tests/workspace.py\nnewman run \"Практические/Отчёты/Agroecosystem.postman_collection.json\"")
h(d, "Вывод", 2)
p(d, "Реализованы фильтры и поиск для трёх сущностей, три метода статистики и один отчёт. Запросы используют связи ORM и SQL-агрегацию. Индексы и ограниченная выдача поддерживают работу с наборами данных, а CSV служит явным форматом обмена.")
save(d, 6)

print("Six practice reports generated")
