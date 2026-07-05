"""Templates plugáveis de folha (docs/DATASET_CONTRACT.md §2): um módulo por família.

Protocolo mínimo: `render_sheet(rng, record, surface, variant) -> RenderResult`
(imagem + `ideal_lines` + fonte usada). Nesta leva só `controle_ocorrencias`;
ronda/portaria entram no futuro, cada um casado com sua config YAML.
"""
