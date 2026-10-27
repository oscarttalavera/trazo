import sys

from trazo.cli import main

if getattr(sys, "frozen", False):
    # Trazo.exe abierto con doble clic: si falla, que la ventana no se cierre sin mostrar el error
    try:
        code = main()
    except Exception as e:  # noqa: BLE001
        print(f"\nError: {e}")
        input("Presione Enter para cerrar...")
        code = 1
    raise SystemExit(code)

raise SystemExit(main())
