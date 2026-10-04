# Limites tecnicos y de interpretacion

## CID, CSD y OCR

Estos registros pertenecen al protocolo SD/MMC. Un adaptador pasivo microSD→SD conserva el protocolo, pero un lector USB suele actuar como puente y presentar un disco USB/SCSI. Si el puente no transmite los comandos SD, ningun programa de usuario puede recuperar el CID real.

En Linux, el caso favorable aparece como `/dev/mmcblk0`; MediaProbe lee, si existen:

```text
/sys/class/block/mmcblk0/device/cid
/sys/class/block/mmcblk0/device/csd
/sys/class/block/mmcblk0/device/ocr
```

Si aparece como `/dev/sdX`, normalmente solo se vera la identidad del lector/puente. Windows no ofrece una API generica y fiable para CID/CSD/OCR de cualquier lector. Un CID plausible tampoco prueba autenticidad: puede copiarse o programarse en controladores falsificados.

## Version y velocidad USB

Hay que separar tres cosas:

1. capacidad del controlador anfitrion (por ejemplo, xHCI);
2. version maxima anunciada por el dispositivo/puente;
3. velocidad realmente negociada en ese puerto y cable.

Linux suele publicar la velocidad negociada en `sysfs` (por ejemplo 480, 5000 o 10000 Mb/s). Windows puede exponer el tipo de bus y el controlador, pero no siempre la velocidad del enlace para dispositivos de almacenamiento. MediaProbe muestra “no expuesta” antes que adivinar. Un benchmark lento no demuestra USB 2.0: la NAND, el controlador, la cache SLC, el lector o el sistema de archivos pueden ser el cuello de botella.

## Cache y resultados

Las pruebas usan sincronizacion de archivos, pero el dispositivo puede conservar cache interna. El resultado incluye el sistema de archivos y corresponde al conjunto dispositivo + lector + puerto + sistema operativo. La caida de rendimiento se estima a partir de tramos escritos y no identifica por si sola la causa. Repita la prueba y observe rendimiento sostenido, no solo picos. El modo tienda de 2 a 5 minutos es un objetivo aproximado: el sistema no puede cancelar una llamada de E/S del controlador que quede bloqueada.

## SMART y temperatura

Muchas memorias flash extraibles no implementan SMART y numerosos puentes USB bloquean sus comandos. MediaProbe usa contadores de almacenamiento disponibles y reconoce `smartctl` si se coloca en `tools/` o en el `PATH`. “No disponible” no significa que la unidad este sana ni defectuosa.

## Capacidad nominal y real

Los fabricantes anuncian GB decimales (1 GB = 1 000 000 000 bytes); Windows suele mostrar GiB binarios. Una unidad de 128 GB normalmente aparece cerca de 119 GiB antes del espacio reservado por el sistema de archivos. MediaProbe separa capacidad anunciada, capacidad fisica/reportada, capacidad del volumen y bytes escritos y releidos correctamente. La prueba segura verifica archivos en el espacio libre, no sectores ocupados o no particionados. Incluso el modo destructivo no es una prueba raw de todos los sectores fisicos ni garantiza autenticidad. Una discrepancia puede deberse a particiones, formato o publicidad enganosa y requiere investigacion.

## Puntuacion, clases y recomendaciones

Los umbrales de clases SD son referencias para interpretar esta sesion, no una certificacion oficial. El host y el lector pueden limitar velocidades e IOPS; A2 tiene requisitos funcionales no verificados por una prueba de archivos. El puntaje propio de MediaProbe no debe usarse como sello de calidad comercial. Las recomendaciones 4K y dashcam son orientativas: se debe comprobar bitrate, compatibilidad y resistencia real de la tarjeta.

## Distribucion y privacidad

La busqueda web opcional usa interfaces publicas de DuckDuckGo que pueden cambiar o bloquear solicitudes automatizadas. Una fuente oficial encontrada corresponde a una referencia comercial, no necesariamente al hardware conectado. Modelo y VID/PID pueden identificar el lector, y los nombres reportados pueden ser manipulados. El numero de serie y CID no se envian al buscador. La ficha y referencias se guardan en el SQLite local. Los porcentajes de rendimiento frente a valores "hasta" no implican incumplimiento de un minimo garantizado. Los informes JSON nuevos usan schema_version 3 y conservan la lectura del historial anterior.

El EXE no esta firmado digitalmente; Windows puede mostrar una advertencia. El historial SQLite se guarda en el perfil local del equipo anfitrion, no en la USB de distribucion, y puede contener identificadores de dispositivos. Para uso comercial formal faltan pruebas de hardware amplio, revision de seguridad, firma de codigo, instalador/soporte y validacion de cumplimiento legal y licencias de herramientas opcionales. El binario Linux debe compilarse y validarse en Linux.
