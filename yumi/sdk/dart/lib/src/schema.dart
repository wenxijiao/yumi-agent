import 'types.dart';

Map<String, dynamic> buildToolSchema(RegisterOptions opts) {
  // Map the `mode` API onto the existing wire flags (one mode per tool).
  var alwaysInclude = opts.alwaysInclude;
  var proactiveContext = opts.proactiveContext;
  var proactiveContextArgs = opts.proactiveContextArgs;
  var proactiveContextDescription = opts.proactiveContextDescription;
  switch (opts.mode) {
    case 'dynamic':
      break;
    case 'pinned':
      alwaysInclude = true;
      break;
    case 'autorun':
      proactiveContext = true;
      if (opts.contextArgs != null) proactiveContextArgs = opts.contextArgs;
      if (opts.contextLabel != null) {
        proactiveContextDescription = opts.contextLabel;
      }
      break;
    default:
      throw ArgumentError(
        "mode must be 'dynamic', 'pinned', or 'autorun'; got '${opts.mode}'",
      );
  }

  final properties = <String, dynamic>{};
  final required = <String>[];
  for (final p in opts.parameters) {
    properties[p.name] = {
      'type': p.typeName,
      'description': p.description,
    };
    final isRequired = p.required_ ?? true;
    if (isRequired) required.add(p.name);
  }

  final schema = <String, dynamic>{
    'type': 'function',
    'function': {
      'name': opts.name,
      'description': opts.description,
      'parameters': {
        'type': 'object',
        'properties': properties,
        'required': required,
      },
    },
  };
  if (opts.timeout != null) {
    schema['timeout'] = opts.timeout;
  }
  if (opts.requireConfirmation) {
    schema['require_confirmation'] = true;
  }
  if (alwaysInclude) {
    schema['always_include'] = true;
  }
  if (opts.allowProactive) {
    schema['allow_proactive'] = true;
  }
  if (proactiveContext) {
    schema['proactive_context'] = true;
  }
  if (proactiveContextArgs != null) {
    schema['proactive_context_args'] = proactiveContextArgs;
  }
  if (proactiveContextDescription != null &&
      proactiveContextDescription.trim().isNotEmpty) {
    schema['proactive_context_description'] = proactiveContextDescription;
  }
  return schema;
}
