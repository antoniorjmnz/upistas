#!/bin/sh
# Ejecutar una vez tras clonar: activa plantilla de commit y hooks del equipo.
git config commit.template .gitmessage
git config core.hooksPath .githooks
git config pull.rebase true
echo "✔ Plantilla de commit y hooks activados"
