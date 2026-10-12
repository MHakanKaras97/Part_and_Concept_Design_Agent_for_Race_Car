"""Component generators. Each generator module provides the same deterministic interface:

GENERATOR_ID, GENERATOR_VERSION, ID_PREFIX, PROCESSES, REQUIRED_INFO, LENGTH_PARAMS, COUNT_PARAMS,
Inputs model (`BracketInputs` for l_bracket, exposed as INPUTS), feasibility_errors(p), dfm_quantities(p),
expected_volume_mm3(p), expected_bbox_local(p), expected_holes_local(p), interfaces(p, ...),
structural_section(p), fusion_parameters(component_id, p), param_prefix(id),
fusion_component_name(id, name), build_script(id, name, p, transform, fusion_material).
"""
from fusion.generators import l_bracket

l_bracket.INPUTS = l_bracket.BracketInputs

GENERATORS = {l_bracket.GENERATOR_ID: l_bracket}
