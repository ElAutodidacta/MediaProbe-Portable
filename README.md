# MediaProbe Portable

Herramienta portátil en español para evaluar memorias microSD, SD, USB y otras unidades de almacenamiento. Incluye interfaz gráfica local, benchmarks, verificación de capacidad, ficha de producto, consultas web, historial e informes.

**Autoría: ASAG — Colaboración con Codex.** Licencia MIT.

## Descargar y empezar

Descargue el paquete Windows de [Releases](https://github.com/ElAutodidacta/MediaProbe-Portable/releases), descomprímalo y abra `MediaProbe-Portable.exe`. En **Producto** introduzca marca, modelo, capacidad y velocidades anunciadas. En **Analizar**, comience con la inspección sin escritura o con Modo tienda.

La interfaz se abre en el navegador mediante un servidor local en `127.0.0.1`. Las pruebas funcionan sin Internet; la consulta de referencias comerciales es opcional. El EXE publicado no está firmado digitalmente.

## Documentación

- [Manual completo en español](README_ES.md)
- [Inicio rápido](INICIO-RAPIDO.txt)
- [Compilación Windows y Linux](COMPILAR.md)
- [Limitaciones e interpretación de resultados](LIMITACIONES.md)
- [Créditos](AUTHORS.md)
- [Licencia MIT](LICENSE.txt)

## Funciones

- Inspección sin escritura, modo tienda de 2/3/5 minutos, benchmark y pruebas de capacidad.
- Lectura/escritura secuencial y aleatoria, archivos pequeños, muestras de velocidad sostenida y caídas de rendimiento.
- Comparación entre datos anunciados y observados; búsqueda de referencias del producto con fuentes y fecha.
- Modelo, serie, VID/PID, controlador, formato, bus y velocidad negociada cuando el sistema la expone.
- Intento de lectura CID/CSD/OCR mediante SD/MMC directo en Linux; SMART y temperatura cuando están disponibles.
- Historial local y exportación TXT, JSON y HTML; el HTML puede imprimirse como PDF.
- Prueba destructiva opcional con comprobación del objetivo y confirmación exacta.

Una muestra correcta no verifica toda la capacidad. Las pruebas de archivos no cubren sectores ocupados o no particionados; los resultados de rendimiento, registros y consultas web no certifican la marca ni los logotipos SD. Consulte el manual antes de usar el modo destructivo.

## Ejecutar desde el código

Requiere Python 3.11 o posterior; la aplicación utiliza la biblioteca estándar durante la ejecución.

```sh
python -m unittest discover -s tests -v
python main.py
```

El código y el script Linux están incluidos; el paquete publicado de esta versión se ha compilado y comprobado en Windows. La compatibilidad de hardware necesita comprobación con la unidad y el lector reales.
