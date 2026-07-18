# Odoo — Contexto de Modulos de Facturacion Electronica

## Que es esta carpeta

Modulos Odoo 18 para integrar facturacion electronica colombiana (DIAN) via la API `facturapi-api`. Cada tipo de documento electronico tiene su propio modulo.

---

## Modulos

```
odoo/
├── l10n_co_facturapi/          # Base: certificado, config empresa, formato EDI, modelo facturapi.document
├── l10n_co_facturapi_data/     # Datos: ciudades, tablas DIAN (medios_pago, responsable_fiscal, etc.)
├── l10n_co_facturapi_fe/       # FE: Factura Electronica (botones, wizard, secuencias, reportes)
├── l10n_co_facturapi_ds/       # DS: Documento Soporte (adquisiciones a no obligados)
├── l10n_co_facturapi_de/       # DE: Documento Equivalente (PENDIENTE)
├── l10n_co_facturapi_nom/      # NOM: Nomina Individual (PENDIENTE — usar OCA payroll)
└── l10n_co_facturapi_radian/   # RADIAN: Eventos (PENDIENTE)
```

### Dependencias entre modulos
```
l10n_co_facturapi_data  (sin dependencias)
        │
l10n_co_facturapi  (depende de: account, account_edi, certificate, account_edi_ubl_cii)
   │        │
   │   l10n_co_facturapi_fe  (depende de: l10n_co_facturapi, l10n_co_facturapi_data, account_move_name_sequence)
   │        │
   │   l10n_co_facturapi_ds  (depende de: l10n_co_facturapi, l10n_co_facturapi_data, l10n_co_facturapi_fe)
```

---

## Modulo Base: `l10n_co_facturapi`

El modulo que todo lo conecta. Proporciona:

### Modelos
- **`facturapi.document`** — Tabla principal que registra cada documento enviado a DIAN. Campos: `document_type`, `document_key`, `cufe`, `cuds`, `qr_code`, `status_code`, etc.
- **`facturapi.api.config`** — Configuracion de la API (URL, API key)
- **`certificate`** — Certificados PFX subidos por el usuario

### Configuracion de empresa (`res.company`)
- Toggle de habilitacion FacturAPI
- URL y API key del backend
- Certificado PFX + password

### EDI Format
- Crea el formato EDI `facturapi_invoice` via `data/edi_format_data.xml`
- `facturapi_edi_format.py` busca el formato correcto por codigo (`invoice`, `support_document`, etc.)

### Cron
- Tarea periodica para consultar estado de documentos pendientes en DIAN
- NOTA: En Odoo 18, `numbercall` no es valido en `ir.cron` (removido de `ir_cron_data.xml`)

---

## Modulo FE: `l10n_co_facturapi_fe`

### Funcionalidad
- Botones "Enviar a DIAN" y "Consultar estado" en facturas
- Wizard de envio (`account_move_send.py`)
- Secuencias de numeracion por rango de fechas (`ir_sequence_date_range.py`)
- Reporte PDF de factura electronica (`report/`)
- Toggle de habilitacion FE por empresa

### Datos
- Resoluciones DIAN de ejemplo en `data/resolution_data.xml`

### Campos en `account.move`
- `l10n_co_cufe` — CUFE calculado
- `l10n_co_qr_code` — QR en base64
- `l10n_co_document_key` — Llave del documento en DIAN
- `l10n_co_status_code` — Codigo de respuesta DIAN
- `l10n_co_status_message` — Mensaje DIAN

### XML Template
- `tools/templates/factura_electronica.xml.jinja` — UBL 2.1 para FE

---

## Modulo DS: `l10n_co_facturapi_ds`

### Funcionalidad
- Documento Soporte en adquisiciones a sujetos excluidos de facturar
- Botones "Enviar DS a DIAN" y "Consultar estado"
- Wizard de envio
- Secuencias DS propias

### Diferencias clave con FE
| Aspecto | FE | DS |
|---------|----|----|
| ProfileID | `DIAN 2.1: facturacion` | `DIAN 2.1: documento soporte...` |
| CustomizationID | 104445 | 10 |
| TypeCode | 01 (venta) | 05 (DS proveedor no obligado) |
| Hash UUID | CUFE (SHA-384) | CUDS (SHA-384) |
| Supplier TaxScheme | `01` (IVA) | `ZZ` (No aplica) |
| Supplier TaxLevelCode | `O-23` | `O-23;O-47` |
| Supplier address | `cac:Party` | `cac:PhysicalLocation` |
| Supplier additional_account_id | — | `1` |
| QR format | `NroFactura=...` | `N°DocSoporte=DS...` |

### Campos en `account.move`
- `l10n_co_cuds` — CUDS calculado
- `l10n_co_ds_qr_code` — QR DS en base64
- `l10n_co_ds_document_key` — Llave DS en DIAN

### XML Template
- `tools/templates/documento_soporte.xml.jinja` (en `facturapi-dian-core`)

---

## Convenciones Odoo 18 (CRITICO)

### XML
- Usar `<list>` en vez de `<tree>`
- Usar expresiones `invisible` en vez de `attrs`:
  ```xml
  <!-- MAL (Odoo 16/17) -->
  <field name="foo" attrs="{'invisible': [('state', '=', 'draft')]}"/>
  
  <!-- BIEN (Odoo 18) -->
  <field name="foo" invisible="state == 'draft'"/>
  ```
- NO usar literal `false` en `invisible` — usar `not field_name` o `field_name == False`
- NO usar `<data>` wrapper dentro de `<odoo>`
- NO usar `states=` en campos — usar `invisible` con condiciones

### Python
- Heredar de `models.Model` normalmente
- Usar `api.depends` para computed fields
- `account_edi.format` es la clase base para formatos EDI

---

## Infraestructura Docker Odoo

**Docker Compose:** `C:\Users\jupar\Documents\GitHub\juanparmer\odoocker\docker-compose.yml`

| Container | Puerto | DB User/Pass/DB |
|-----------|--------|-----------------|
| `odoo-web-1` | 8069 | — |
| `odoo-db-1` | 5432 | `odoo`/`odoo`/`admin` |

### Montar modulos en Odoo
Los modulos se montan via volumes en el Docker de Odoo. Verificar que las rutas en `docker-compose.yml` apunten a `odoo/` correctamente.

### Instalar un modulo
```bash
# Via UI:
# Settings > Apps > Buscar "FacturAPI" > Instalar

# Via CLI:
docker exec -it odoo-web-1 odoo -d admin -i l10n_co_facturapi --stop-after-init
```

---

## COMO PROBAR

### Verificar que los modulos estan instalados
```sql
-- Conectar a la BD de Odoo:
SELECT name, state FROM ir_module_module WHERE name LIKE 'l10n_co_facturapi%';
```

### Verificar columnas en account_move
```sql
SELECT column_name FROM information_schema.columns 
WHERE table_name = 'account_move' AND column_name LIKE 'l10n_co_%';
```

### Verificar formatos EDI
```sql
SELECT code, name FROM ir_edi_format WHERE code LIKE 'facturapi%';
```

---

## Pendiente

- [ ] Modulo DE (`l10n_co_facturapi_de`) — Documento Equivalente
- [ ] Modulo NOM (`l10n_co_facturapi_nom`) — usar OCA `payroll` como base
- [ ] Modulo RADIAN (`l10n_co_facturapi_radian`) — modelo nuevo `facturapi.radian.event`
- [ ] Tests automatizados
- [ ] Reports para DS
