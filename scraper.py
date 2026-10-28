name: Radar Vuelos Suiza (Coste Cero)

on:
  schedule:
    - cron: '0 */3 * * *'
  workflow_dispatch:
    inputs:
      forzar_correo:
        description: 'Forzar envio de correo para prueba'
        required: false
        type: boolean
        default: false

permissions:
  contents: write

concurrency:
  group: "radar-job"
  cancel-in-progress: false

jobs:
  ejecutar-rastreador:
    runs-on: ubuntu-latest

    steps:
      - name: Descargar repositorio
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Configurar Python 3.11
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'

      - name: Instalar dependencias
        run: |
          pip install -r requirements.txt

      - name: Ejecutar Rastreador Multiaerolinea
        env:
          SENDER_EMAIL: ${{ secrets.SENDER_EMAIL }}
          SENDER_PASSWORD: ${{ secrets.SENDER_PASSWORD }}
          RECIPIENT_EMAIL: ${{ secrets.RECIPIENT_EMAIL }}
          FORZAR_CORREO: ${{ inputs.forzar_correo }}
          PAGES_URL: "https://${{ github.repository_owner }}.github.io/${{ github.event.repository.name }}"
        run: |
          python scraper.py

      - name: Guardar Historial y Web en Git
        uses: stefanzweifel/git-auto-commit-action@v5
        with:
          commit_message: "chore(radar): actualizar vuelos multiaerolinea [skip ci]"
          file_pattern: "data/* index.html"
