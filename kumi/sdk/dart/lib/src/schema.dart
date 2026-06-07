import 'types.dart';

Map<String, dynamic> buildToolSchema(RegisterOptions opts) {
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
  if (opts.alwaysInclude) {
    schema['always_include'] = true;
  }
  if (opts.allowProactive) {
    schema['allow_proactive'] = true;
  }
  if (opts.proactiveContext) {
    schema['proactive_context'] = true;
  }
  if (opts.proactiveContextArgs != null) {
    schema['proactive_context_args'] = opts.proactiveContextArgs;
  }
  if (opts.proactiveContextDescription != null &&
      opts.proactiveContextDescription!.trim().isNotEmpty) {
    schema['proactive_context_description'] = opts.proactiveContextDescription;
  }
  return schema;
}
