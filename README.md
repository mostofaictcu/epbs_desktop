# EPBS Desktop (PostgreSQL 18 edition)

A Python desktop replacement for the legacy Windows EPBS / CU Electric Billing
application (VB.NET + MySQL). It keeps the old business rules and database
layout, but runs on **PostgreSQL 18** with a **PySide6 (Qt)** interface.

Features:

- Windows-style **Home screen** with large icon tiles for each section, plus
  quick actions (Excel backup, change password, about) and a status strip.
- **Master data** screen for consumer types/rates, optional progressive slab
  tariffs, per-type meter rent, areas, departments, designations and consumer
  groups (add, rename, delete with usage checks).
- Consumer database: search by account number, meter number or name; add,
  edit, delete, Excel import.
- Bill generation with an on-screen summary of **units used and total price**.
- Per-consumer rate override, consumer-type flat rates and optional progressive
  slab tariffs with per-type meter rent.
- **Unit change / rate change** screen with audit trail, bill recalculation and
  optional re-pricing of open bills.
- Payments, dues and receipts.
- Ink-optimised bills, statements and reports: black on white, thin borders,
  small configurable font, **no filled backgrounds**.
- **Direct printing** to the configured/default printer, optional print dialog,
  and PDF output.
- Reports: bills register, collections, dues by consumer/area/type, consumer
  list, monthly billing summary.
- Excel: full combined database workbook, per-report export, consumer import.
- **Background export queue**: Excel and PDF files are generated one at a time
  in a worker thread while a dockable job log shows progress and results, so
  the window never freezes.
- Record lists (consumers, bills, consumer history and detail reports) use
  **keyset (cursor) pagination**, so only one page is loaded at a time.
- Legacy MySQL → PostgreSQL migration tool that preserves ids and passwords.

---

## 1. Requirements

- Windows 10/11 (also runs on Linux/macOS)
- Python 3.10+ (tested with Python 3.12)
- PostgreSQL 18 reachable from the PC
- A printer if you want direct printing (PDF works without one)

Python packages (`requirements.txt`):

```
PySide6>=6.6
psycopg[binary]>=3.1
openpyxl>=3.1
Jinja2>=3.1
PyMySQL>=1.1      # only for the migration tool
```

Install:

```bat
cd /d "F:\engineering_office\Sign In IT\EPBS_Desktop"
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Create the PostgreSQL database

Create an empty database (the app creates its tables automatically):

```sql
CREATE DATABASE ebps_db;
```

or from a terminal:

```bat
createdb -U postgres ebps_db
```

Edit `config.ini` (or use **Settings → Database** in the app):

```ini
[database]
host = localhost
port = 5432
dbname = ebps_db
user = postgres
password = your-password
sslmode = prefer
schema = public
connect_timeout = 5
```

Keep `config.ini` private: the password is stored in plain text.

Like the legacy MySQL database, the PostgreSQL schema intentionally does
**not** create `FOREIGN KEY` constraints. This allows CSV imports in any table
order. The application performs its own checks (for example it refuses to
delete a consumer that still has bills).

On first start the app creates the schema and seed data. Default logins:

| Username | Password | Access |
|----------|----------|--------|
| `Admin` | `123456` | Administrator |
| `operator` | `123456` | Operator (billing) |

Change the password from **File → Change password**.

## 3. Start the application

```bat
python main.py
```

or double-click `run.bat` (it activates `.venv` when present).

Set `EPBS_CONFIG` to use a different configuration file:

```bat
set EPBS_CONFIG=D:\epbs\config.ini
python main.py
```

If the database cannot be reached, a connection dialog opens so the
credentials can be corrected without editing the file by hand.

## 4. Daily work

### Home screen

After login the app opens on **Home**: a start screen with one large block per
section (Consumers, Generate bill, Bills & payments, Unit / rate change,
Reports & Excel, Dashboard, Master data, Settings). Click a block — or press
`Tab` until it is highlighted and press `Enter` — to open that section. Every
section is also available from the tab bar at the top, which uses the same
icons.

The button row under the tiles provides **Backup to Excel**, **Change
password** and **About EPBS**, while the right side shows the database,
printer, paper size and ink-saver status.

Each section has its own accent colour: the Home tiles show a coloured top
strip, icon plate and title, the tab icons use the same colour, and the
dashboard cards are tinted per figure (consumers blue, active green, unpaid
amber, outstanding rose, collected teal, billed indigo). Status words in
lists are coloured too – green for *Paid* / *Active*, red for *Unpaid*, grey
for *Inactive*. This is screen-only styling: printed bills, statements and
reports stay black on white for the ink saver.

The window opens maximized. **View → Full screen** (or `F11`) toggles a
borderless full-screen view; press `F11` or `Esc` to return. The crest on the
login dialog and Home banner plays the animation built into `logo.svg` once
(the silhouette first, then the crest detail).

### Master data

**Master data** tab edits the lists used by the consumer form. The **Settings**
tab has an **Edit master data...** shortcut to the same screen:

- **Types** – name, flat rate, default meter rent, minimum amount and optional
  slabs (for example `RES-QUATER`). A type with no slabs is billed at the flat
  rate.
- **Areas**, **Departments**, **Designations** – plain name lists.
- **Groups** – consumer groups, with a count of how many consumers use each one.

Slab tariffs are progressive: select a type and press **Slabs...**. Each slab
has a unit range and a rate. For 500 units with `0-400 @ 7.48` and
`401-600 @ 10.20`, the bill is `400 × 7.48 + 100 × 10.20 = 4,012.00`. The last
slab may be left open-ended (To = *No upper limit*); otherwise consumption above
the last ended slab continues at that slab's rate. Meter rent is a fixed amount
added once to the bill and defaults to `0` per type. A per-consumer rate
override bypasses the slab tariff and bills that consumer at one flat rate.

Each type also has an optional **minimum amount** (default `0` = no minimum).
If the calculated energy charge is lower than the minimum, the bill uses the
minimum instead — for example a calculated `200.00` with a `750.00` minimum is
billed at `750.00`. Meter rent and previous dues are added after the minimum.
The applied minimum is stored on the bill (`tbl_bills.minimum_charge`) and
shown as **Minimum charge** on the printed bill.

Use **Add**, **Edit** (or double-click) and **Delete**. Names are matched
case-insensitively, so adding an existing name selects the existing row instead
of creating a duplicate. A master value that is still used by a consumer
cannot be deleted. Renaming a group updates every consumer that uses it.

Groups can also be created directly from the consumer form: choose the group
combo, type a new name and press the **+** button (or just type and save). The
new group is added to the master list and appears in the dropdown next time.

### Confirmation prompts

Every action that writes or removes data asks first; **No** is the default
button, so pressing Enter or Esc cancels:

- **Save** (title *Confirm save*): consumer add/edit, status change, Excel
  import, group creation, master add/rename, new bill, payment collection,
  reading correction, rate change/clear, company information, settings file,
  database connection, schema upgrade and password change.
- **Delete** (title *Confirm delete*): consumers, bills and master values. The
  prompt names the record and warns that the action cannot be undone.

Each prompt summarises the change (record, amount, date or new value), so a
typo or a wrong row is caught before the database is touched.

### Consumers

**Consumers** tab: search by account, meter number or name, then open the
record to edit. Rates can be set per consumer (type rate is used when empty).
**Import from Excel...** accepts an `.xlsx` file with a `Consumers` sheet (or
the active sheet) and these headers (case-insensitive):

```
Account, Name, Address, Meter, Contact, Type, Area, Department,
Designation, Group, Status, Rate override
```

`Account` and `Name` are required. Missing area/department/designation/type
values are created automatically. Existing accounts are updated.

### Generate a bill

**Generate bill** tab:

1. Enter the meter number or account number and press search.
2. The consumer details and the last reading are shown.
3. Enter the present reading and date. Tick **Bookmark this last date
   (continue billing)** to reuse the same last date for the next bills and
   after restarting EPBS; it is stored in `config.ini`. Clear the box to start
   each session from today's date.
4. **Rate** starts at the consumer's current rate (override or type rate). When
   the type has a slab tariff, the rate is shown as the average for the units
   used and the summary lists each slab. Tick **Bill at a flat rate** to ignore
   the slab tariff for this bill. **Save this rate for this customer** (ticked
   by default) also stores a flat rate as the consumer's own rate; clear the
   box to use the rate only for this bill.
5. The summary shows previous/present units, **units used**, the slab breakdown
   (or flat rate), bill amount, minimum amount, previous due, meter rent and
   **total payable**. When the calculated charge is below the type's minimum,
   the bill amount is raised to the minimum and the summary explains why.
   Meter rent starts at the selected type's own default (normally `0`).
6. **Generate bill** saves the bill; **Print** / **PDF** output the ink-saver
   bill. A bill can also be printed later from **Bills & payments**.

The rate used at generation time is stored on the reading (for a slab bill this
is the average rate), so later rate changes do not silently alter old bills.
The applied slab lines are kept in `tbl_bill_slab` for reprints and
recalculation. A rate saved from this screen is written to `tbl_audit` like any
other rate change.

### Unit change / rate change

**Unit / rate change** tab:

1. Search by account number or meter number.
2. Choose a reading and correct the previous/present units.
3. Choose a rate scope:
   - **This consumer** – stores a per-consumer rate override.
   - **Consumer type** – changes the rate for the whole type.
   - **Selected reading only** – re-prices the linked bill without changing
     future rates.
4. Optionally **recalculate the linked bill** and/or **re-price unpaid bills**
   of the consumer (useful after a correction).
5. The summary shows units, rate, amount and total before saving.
6. Every change is written to `tbl_audit` and visible in the audit list.

### Bills & payments

Search/filter bills, open a bill, print/PDF it, record a payment, view payment
history, delete a payment or an unpaid bill, and batch-print filtered bills.
The bill detail shows units and total price.

### Reports & Excel

Choose a report, set the optional date/status/month filters, then:

- **Excel** – export the current report.
- **PDF** – export the current report as a one-sheet PDF.
- **Print** – print the report with the same ink-saver style.
- **Backup workbook** (also **File → Backup database to Excel...**) – one
  workbook with every table: Consumers, Bills, BillDetails, UnitReadings,
  Payments, Types, TypeSlabs, BillSlabs, Areas, Departments, Designations,
  ConsumerGroups, Company, Users, Audit.

Report exports are monochrome, with no fills and thin borders.

### Background exports (job queue)

Excel and PDF exports never block the window. Every export – report Excel,
report PDF, bill PDF, statement PDF and the full database workbook – is put on
a queue and generated **one at a time, in the order you asked for them**, by a
background worker. You can keep searching, editing and generating bills while
a large PDF renders.

- The **Job log** panel opens automatically at the bottom of the window as soon
  as something is queued. It shows the queue state, a progress bar, and a
  timestamped line for every step: *Queued*, *Started*, each work message,
  *Done … (3.4 s) — PDF saved: bills_register.pdf · 800 rows · 295 KB* or
  *FAILED*.
- **Open last file** opens the file that was just written; **Clear log** empties
  the view (the queue keeps running).
- **View → Job log** (or `Ctrl+J`) hides and shows the panel. Closing it does
  not stop the queue; it reopens on the next export.
- The status bar shows the queue length while jobs are pending and a short
  note with the elapsed time when one finishes.
- A failing export is reported in the log and the queue carries on with the
  next job – one bad file never stops the rest.
- If you close the window while exports are pending, EPBS asks first and then
  finishes them before exiting.

**Print** (the physical printer) is still done immediately on the window, so
the Windows print dialog behaves normally; only file generation is queued.

## 5. Printing and ink saving

All documents are written as **Jinja2 templates** in `epbs/templates/` and
rendered by Qt. `printing.py` only prepares the data, so the layout and
stylesheet can be redesigned without touching Python:

- black text on white, no background colours or shaded headings;
- **dashed** 1 px borders and compact padding instead of solid frames;
- body font defaults to 8 pt (6–12 pt can be configured), small margins;
- A4, A5, Letter or 80 mm receipt paper for reports and statements;
- **bills print on A4 portrait sheets** with dashed 1 px borders and compact
  spacing to save ink;
- a single bill prints **once in the top half** of an A4 portrait sheet; the
  bottom half stays blank, separated by a labelled dashed **CUT HERE** line,
  so the sheet can be cut and the free half reused for another bill;
- **Print selected bills** places two different bills on one A4 sheet with the
  same cut line (an odd last bill leaves the bottom half free);
- the printed logo is converted to a light grey, **centred below the company
  name and address** and printed larger (60 px) so it stays readable in the PDF;
- the signature line is dashed and sized to the signature text.

### Company logo

Two crests ship with the application:

| File | Used for |
|------|----------|
| `static/images/logo.svg` | default screen logo: login dialog, Home banner, window/taskbar icon, About box |
| `static/images/company_logo.jpg` | default printed logo: bills, statements, reports and PDF export |

A logo chosen in **Settings → Company information** always wins. Leave the
field empty (or press **Use default**) to fall back to the bundled crest. If a
custom `.svg` is selected, the JPG crest is used for printing and PDF so the
document renders reliably in Qt; other custom formats are used as-is.

`Settings → Printing`:

- **Printer** – blank uses the Windows default printer; otherwise pick one
  from the list.
- **Show print dialog** – when off, **Print** sends the document directly to
  the chosen/default printer. Turn it on to choose a printer or page range
  each time.
- **Font size**, **paper size** (reports and statements; bills print as
  half-A4 sections on A4 portrait sheets unless the receipt roll is selected),
  **copy label**. Meter rent and the minimum amount are
  not global settings: each consumer type has its own values (default 0).
  Meter rent can still be changed for a single bill on the **Generate bill**
  page.

PDF export uses the same HTML and the same two-up renderer as the printer, so
the PDF page and the printed page are identical (A4 portrait, two bills, cut
line and logo included). No printer is needed. A confirmation dialog shows the
full path of every PDF that is saved.

## 6. Excel database export / import

- **Combined workbook**: File → *Backup database to Excel...*. Each table is a
  separate sheet with a header row, auto-filter, frozen header and monochrome
  formatting. User passwords are exported as `encrypted`, not in clear text.
- **Per-report export**: Reports & Excel → *Excel*.
- **Consumer import**: Consumers → *Import from Excel...*. Importing a backup
  workbook's `Consumers` sheet updates existing accounts by account number,
  so an export → edit → import round trip works.

### Manual CSV import (psql `\copy`)

Because the schema has no foreign keys, tables can be loaded in any order:

```bat
psql -U postgres -d ebps_db -c "\copy tbl_consumer FROM 'consumers.csv' CSV HEADER"
psql -U postgres -d ebps_db -c "\copy tbl_bills FROM 'bills.csv' CSV HEADER"
```

`tbl_unit.units` is a generated column. Omit it from CSV files and provide
`previous_unit` / `present_unit` instead.

If the CSV includes explicit values for identity columns (`bill_no`,
`un_id`, `payment_id`, ...), move the sequences past the imported maximum so
new rows do not collide:

```sql
SELECT setval(pg_get_serial_sequence('tbl_bills', 'bill_no'),
              (SELECT max(bill_no) FROM tbl_bills));
SELECT setval(pg_get_serial_sequence('tbl_unit', 'un_id'),
              (SELECT max(un_id) FROM tbl_unit));
SELECT setval(pg_get_serial_sequence('tbl_payment', 'payment_id'),
              (SELECT max(payment_id) FROM tbl_payment));
```

Repeat for `tbl_bills_details.bill_det_id`, `tbl_type.type_id`,
`tbl_area.area_id`, `tbl_department.dep_id`, `tbl_designation.des_id`,
`tbl_customize_bill.cus_bill_no` and
`tbl_customize_bill_details.cus_det_id` when those are imported with ids.
`tbl_consumer.con_id` is a plain integer (no sequence).

The application also repairs these sequences by itself: every start-up
(`Database.initialize_schema`) moves each identity sequence past `MAX(id)`.
The lookup also handles sequences that are not `OWNED BY` the column (plain
`DEFAULT nextval(...)`), which is common after a restore.

Bill generation has three attempts, so a bad sequence can never stop a bill:

1. normal insert (identity allocates the ids);
2. repair all sequences, then insert again;
3. insert with ids computed as `MAX(id) + 1` (the bill/reading tables are
   locked for that transaction). This works even when the column has no
   usable sequence or default at all.

**Settings → Database → Repair ID sequences** runs the repair on demand and
reports how many sequences were moved. When start-up repaired something, the
status bar says so.

The SQL above is therefore only needed when importing while the application
is open in another session.

## 7. Migrating the legacy MySQL database

The old dump `EPBS\ebps_db_no_views.sql` can be imported into MySQL, then
copied to PostgreSQL with the included tool.

Example (MySQL on `localhost:3306`, PostgreSQL from `config.ini`):

```bat
python tools\migrate_from_mysql.py ^
  --mysql-host localhost --mysql-port 3306 ^
  --mysql-user root --mysql-password secret ^
  --mysql-db ebps_db
```

Options:

- `--pg-config PATH` – use another `config.ini`.
- `--replace` – delete existing business rows first (children first). Use only
  on a fresh or disposable target.
- Without `--replace`, rows that already exist are kept (`ON CONFLICT DO
  NOTHING`).

What the tool does:

1. Creates/upgrades the PostgreSQL schema.
2. Matches areas, departments, designations and consumer types **by name**
   (case/space-insensitive), inserting legacy master rows that do not exist.
3. Copies users, company info, consumers, bills, bill details, readings,
   payments and customised bills, preserving legacy ids.
4. Advances all identity sequences so new records do not collide with legacy
   ids.

Legacy users keep their old passwords (the old reversible cipher is supported
by the login screen). Tested against the supplied dump:

| Table | Rows copied |
|-------|-------------|
| Consumers | 1,545 |
| Bills | 34,943 |
| Bill details | 34,943 |
| Meter readings | 34,318 |
| Payments | 35,594 |

## 8. Configuration reference

`config.ini`:

```ini
[database]
host = localhost
port = 5432
dbname = ebps_db
user = postgres
password =
sslmode = prefer          ; disable, allow, prefer, require, verify-ca, verify-full
schema = public
connect_timeout = 5

[app]
company_id = 1001
paper = A4                ; A4, A5, Letter, Receipt 80mm
font_pt = 8.0             ; 6 - 12
printer =                 ; empty = system default
show_print_dialog = 0
auto_schema = 1
bill_copy_label =
```

Settings changed in the GUI are saved back to `config.ini`.

## 9. Folder layout

```
EPBS_Desktop/
  main.py                  launcher
  run.bat                  Windows quick start
  config.ini               local configuration (keep private)
  requirements.txt
  epbs/
    config.py              config.ini load/save
    db.py                  psycopg connection, transactions, schema init
    schema.py              PostgreSQL schema + seed data
    security.py            legacy reversible password cipher
    services.py            business logic, reports, Excel datasets, auth
    printing.py            document data + Qt print/PDF (renders the templates)
    templates/
      base.html            page skeleton shared by all documents
      _header.html         company name, address and light grey logo
      bill.html            half-A4 bill layout
      statement.html       consumer statement layout
      report.html          report table + footer totals
      style.css            shared ink-saving print stylesheet
    excelio.py             workbook export, report export, consumer import
    jobs.py                background FIFO queue (one worker thread)
    theme.py               Qt style
    ui/
      home.py              Windows-style start screen (tiles)
      icons.py             vector icons drawn with QPainter
      jobs.py              job log dock (queue status, log, open last file)
      export_jobs.py       queued Excel/PDF work functions
      masters.py           master data editor (types, areas, groups, ...)
      ...                  tabs and dialogs
  tools/
    migrate_from_mysql.py  legacy MySQL -> PostgreSQL migration
```

## 10. Troubleshooting

- **Connection refused / timeout** – check the PostgreSQL service, port,
  `pg_hba.conf` and that the database exists. Use **Settings → Test connection**
  or the dialog shown at startup.
- **No printer is installed** – PDF export still works; set a printer in
  Settings or install one.
- **Qt platform plugin error** – reinstall PySide6 in the same Python
  environment (`pip install --force-reinstall PySide6`). On a headless server,
  run with a desktop session; the app needs a GUI.
- **Legacy login fails after migration** – users keep their old MySQL
  passwords. Use `Admin` / `123456` only if the legacy Admin password was
  `123456`; otherwise use the old password. Passwords can be reset by an
  administrator through **File → Change password**.
- **Import says the account must be numeric** – the account/consumer id in the
  sheet must contain digits only (legacy ids are integers).
- **`duplicate key value violates unique constraint "tbl_unit_pkey"`** (or
  `tbl_bills_pkey`) – an id sequence still points at an id that already exists.
  Open **Settings → Database → Repair ID sequences** (or restart the app) and
  try again; bill generation also repairs the sequences and falls back to
  explicit ids by itself.

## Security note

The legacy password cipher is reversible to remain compatible with the old
database; it is not strong cryptography. Keep `config.ini` and any Excel
backup private, and restrict access to the PostgreSQL server.
