public Object complete(JsonParser p, DeserializationContext ctxt,
            PropertyValueBuffer buffer, PropertyBasedCreator creator)
        throws JacksonException
    {
        // first things first: deserialize all data buffered:
        final int len = _properties.length;
        Object[] values = new Object[len];
        final Class<?> activeView = ctxt.getActiveView();
        for (int i = 0; i < len; ++i) {
            String typeId = _typeIds[i];
            final ExtTypedProperty extProp = _properties[i];
            // [databind#6055]: if the value property is filtered out by the active
            // JsonView, skip it entirely -- leave value null instead of binding the
            // buffered value or reporting the external type id as missing.
            if ((activeView != null) && !extProp.getProperty().visibleInView(activeView)) {
                continue;
            }
            if (typeId == null) {
                // let's allow missing both type and property (may already have been set, too)
                TokenBuffer tb = _tokens[i];
                if ((tb == null)
                        // 19-Feb-2021, tatu: Both missing value and explicit `null`
                        //    should be accepted...
                        || (tb.firstToken() == JsonToken.VALUE_NULL)
                    ) {
                    continue;
                }
                // [databind#3786]: Need to mind natural types, for which no type id
                // will be included.
                JsonToken t = tb.firstToken();
                if (t.isScalarValue()) {
                    JsonParser buffered = tb.asParser(ctxt, p);
                    buffered.nextToken();
                    SettableBeanProperty prop = extProp.getProperty();
                    Object result = TypeDeserializer.deserializeIfNatural(buffered, ctxt, prop.getType());
                    if (result != null) {
                        values[i] = result;
                        // Unlike bean-based complete(), creator-based needs
                        // to assign parameter to buffer before continuing
                        if (prop.isCreatorProperty()) {
                            buffer.assignParameter(prop, result);
                        }
                        continue;
                    }
                }
                // 26-Oct-2012, tatu: As per [databind#94], must allow use of 'defaultImpl'
                if (!extProp.hasDefaultType()) {
                    ctxt.reportPropertyInputMismatch(_beanType, extProp.getProperty().getName(),
                            "Missing external type id property '%s'",
                            extProp.getTypePropertyName());
                } else {
                    typeId = extProp.getDefaultTypeId(ctxt);
                }
            }

            if (_tokens[i] != null) {
                values[i] = _deserialize(p, ctxt, i, typeId);
            } else {
                if (ctxt.isEnabled(DeserializationFeature.FAIL_ON_MISSING_EXTERNAL_TYPE_ID_PROPERTY)) {
                    SettableBeanProperty prop = extProp.getProperty();
                    ctxt.reportPropertyInputMismatch(_beanType, prop.getName(),
                            "Missing property '%s' for external type id '%s'",
                            prop.getName(), _properties[i].getTypePropertyName());
                }
                // 03-Aug-2022, tatu: [databind#3533] to handle absent value matching
                //    present type id
                values[i] = _deserializeMissingToken(p, ctxt, i, typeId);
            }

            final SettableBeanProperty prop = extProp.getProperty();
            // also: if it's creator prop, fill in
            if (prop.isCreatorProperty()) {
                buffer.assignParameter(prop, values[i]);

                // [databind#999] And maybe there's creator property for type id too?
                SettableBeanProperty typeProp = extProp.getTypeProperty();
                // for now, should only be needed for creator properties, too
                if (typeProp != null && typeProp.isCreatorProperty()) {
                    // 31-May-2018, tatu: [databind#1328] if id is NOT plain `String`, need to
                    //    apply deserializer... fun fun.
                    final Object v;
                    if (typeProp.getType().hasRawClass(String.class)) {
                        v = typeId;
                    } else {
                        TokenBuffer tb = ctxt.bufferForInputBuffering(p);
                        tb.writeString(typeId);
                        v = typeProp.getValueDeserializer().deserialize(tb.asParserOnFirstToken(ctxt), ctxt);
                        tb.close();
                    }
                    buffer.assignParameter(typeProp, v);
                }
            }
        }
        Object bean = creator.build(ctxt, buffer);
        // third: assign non-creator properties
        for (int i = 0; i < len; ++i) {
            SettableBeanProperty prop = _properties[i].getProperty();
            if (!prop.isCreatorProperty()) {
                prop.set(ctxt, bean, values[i]);
            }
        }
        return bean;
    }