# MediaProbe Portable 1.2

Aplicacion grafica en espanol para evaluar memorias USB y tarjetas microSD con pruebas conservadoras y resultados explicables. Funciona sin instalar controladores ni servicios.

**Autoría: ASAG — Colaboración con Codex.** Licencia MIT. Consulte [AUTHORS.md](AUTHORS.md) para los créditos.

El código completo y la documentación están en este repositorio. Los ejecutables y paquetes portátiles se distribuyen desde [Releases](https://github.com/ElAutodidacta/MediaProbe-Portable/releases). El ejecutable de Windows funciona sin instalar Python; para Linux se incluye el código y el script de compilación.

## Inicio rapido (Windows)

1. Descomprima el paquete completo en una memoria USB o carpeta local.
2. Abra `MediaProbe-Portable.exe`. La aplicacion inicia un servidor exclusivamente local (`127.0.0.1`) y abre la interfaz en su navegador.
3. Conecte la memoria que desea revisar y pulse **Actualizar**.
4. Seleccione la unidad correcta. **Inspeccionar sin escribir** consulta identidad y estado sin crear archivos.
5. Para una compra en tienda, use **Modo tienda** (objetivo 2, 3 o 5 minutos). Para ampliar la evidencia, use benchmark sostenido y **Verificar todo el espacio libre**.
6. En **Producto**, indique tipo, marca, modelo/SKU, capacidad y velocidades anunciadas. Distinga "hasta" de un minimo sostenido. La ficha se guarda por dispositivo y se compara con los resultados en Resumen, informes e historial. Añada las clases impresas en Analizar.
7. Exporte TXT, JSON y HTML; el HTML puede imprimirse como PDF. **Historial** permite comparar pruebas anteriores.

No necesita instalacion. Las pruebas funcionan sin Internet; la consulta de referencias del producto requiere conexion. Windows puede pedir permiso para consultar datos de almacenamiento; la prueba segura no necesita formatear la unidad.

## Consulta automatica de productos

Al seleccionar una unidad o guardar su ficha, la aplicacion busca referencias publicas con DuckDuckGo Lite/HTML. Prioriza dominios reconocidos de fabricantes y explica las coincidencias por marca, modelo y capacidad. Si el modelo detectado es informativo y difiere del indicado, realiza una consulta adicional; un aviso explica que ese modelo puede identificar el lector/puente. Puede desactivar la busqueda automatica o pulsar Buscar de nuevo. Tambien admite una URL HTTPS de un fabricante reconocido para consultar directamente una ficha HTML.

Se envian marca, modelo publico y capacidad. No se envian archivos, serial, unique ID, CID/CSD/OCR ni mediciones del benchmark. Los resultados se guardan en el perfil del equipo junto con la ficha. Una consulta correcta se reutiliza durante 6 horas para reducir peticiones; Buscar de nuevo la actualiza. Si se pierde la conexion, se muestran las referencias guardadas con su fecha y el aviso correspondiente. Un buscador puede pedir CAPTCHA, bloquear peticiones o cambiar su formato; el programa muestra el fallo y ofrece abrir la busqueda manual. Una coincidencia web no autentica una unidad ni cambia automaticamente los datos declarados o la puntuacion tecnica. La marca indicada por el usuario y los dominios conocidos no son pruebas criptograficas de identidad.

## Pruebas incluidas

- escritura y lectura secuencial con verificacion de datos, muestras de rendimiento sostenido y aviso de caida tras posible agotamiento de cache;
- lectura/escritura aleatoria de 4 KiB (IOPS y MB/s);
- creacion/lectura de muchos archivos pequenos;
- muestra de capacidad (hasta 2 GiB), modo tienda temporizado (hasta 256 MiB de muestra) o llenado seguro de todo el espacio libre;
- modo destructivo opcional que borra contenidos y verifica casi todo el volumen;
- modelo, serie, VID/PID, tipo de bus, sistema de archivos, capacidad anunciada, reportada y realmente verificada;
- velocidad USB negociada en Linux cuando `sysfs` la expone; en Windows se evita deducirla sin evidencia;
- CID/CSD/OCR en Linux cuando la tarjeta aparece directamente como `mmcblk`;
- SMART/temperatura e indicadores de errores de medio cuando el hardware los expone, con `smartctl` opcional;
- umbrales observados frente a C10, U1, U3, V10, V30, V60, V90, A1 y A2; estimacion de llenado y recomendaciones cautas de uso;
- informe TXT/JSON/HTML, historial SQLite local y puntuacion tecnica con nivel de confianza.

## Seguridad

Cuando un extracto oficial coincidente contiene una pareja explicita de velocidades de lectura/escritura, se muestra como referencia y se avisa si difiere de lo indicado. No todos los sitios publican esos datos en el extracto; revise siempre la ficha completa y la variante. Ninguna referencia rellena ni cambia la ficha automaticamente.

Las pruebas seguras crean una carpeta `.mediaprobe-test/sesion-...` de nombre unico. Nunca abren un archivo existente para escritura. Conservan una reserva de 512 MiB en la prueba completa y retiran los temporales al acabar o al pulsar **Detener**. La inspeccion solo lectura no crea esos archivos. El historial se guarda en el perfil del equipo anfitrion, no en la memoria examinada; puede contener modelo, serie y resultados, por lo que debe retirarse manualmente del equipo si se requiere privacidad.

El modo destructivo:

- solo se habilita para una unidad informada como extraible;
- bloquea el disco del sistema;
- muestra montaje, modelo, serie y capacidad;
- exige una frase que contiene la unidad y serie/numero de disco;
- vuelve a enumerar la unidad y compara montaje, numero de disco, serie y capacidad;
- borra archivos accesibles, pero no cambia tabla de particiones ni formatea.

Use el modo destructivo unicamente con permiso del propietario. El borrado es irreversible y algunos archivos protegidos por el sistema pueden impedir una cobertura total.

## Interpretacion responsable

La clase mostrada es **compatible segun rendimiento medido**, no una certificacion SD Association. A1 usa como referencia 1500 IOPS de lectura, 500 IOPS de escritura y 10 MB/s secuenciales; A2 usa 4000/2000/10, pero MediaProbe no certifica Command Queueing. V30/V60/V90 se comparan con 30/60/90 MB/s de escritura observada.

Una prueba por muestra correcta no demuestra la capacidad completa. Una prueba completa segura solo cubre el espacio libre; si los archivos existentes ocupan parte apreciable del volumen, la conclusion sigue siendo provisional. Para acercarse a todo el volumen hay que vaciarlo o usar el modo destructivo. Este ultimo tampoco verifica espacio no particionado ni todos los sectores fisicos. Ninguna prueba de corta duracion mide endurance, ciclos de escritura, garantia ni autenticidad del canal de venta. El modo tienda tiene un presupuesto aproximado, no un limite duro: una llamada de E/S bloqueada puede superar el tiempo elegido.

La puntuacion de 0 a 100 es un indice comparativo propio, no una certificacion ni un indicador de probabilidad de falsificacion. Compare resultados solo entre pruebas con el mismo lector, puerto y metodo. Un dispositivo puede fallar por lector, puerto, cable, formato o temperatura; repita las pruebas antes de atribuir el problema a la tarjeta.

Consulte [LIMITACIONES.md](LIMITACIONES.md) para CID y USB, y [COMPILAR.md](COMPILAR.md) para reproducir los binarios.
