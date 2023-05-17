from typing import Any, Optional, Union, cast, overload

import marie.check as check
from marie._annotations import public
from marie._builtins import BuiltinEnum
from marie._config import UserConfigSchema
from marie._core.errors import DagsterInvalidConfigError, DagsterInvalidDefinitionError
from marie.serdes import serialize_value
from marie.utils import is_enum_value
from marie.utils.typing_api import is_closed_python_optional_type, is_typing_type

from .config_type import Array, ConfigAnyInstance, ConfigType, ConfigTypeKind
from .field_utils import FIELD_NO_DEFAULT_PROVIDED, Map, all_optional_type


def _is_config_type_class(obj) -> bool:
    return isinstance(obj, type) and issubclass(obj, ConfigType)


def helpful_list_error_string() -> str:
    return "Please use a python list (e.g. [int]) or dagster.Array (e.g. Array(int)) instead."


VALID_CONFIG_DESC = """
1. A Python primitive type that resolve to dagster config
   types: int, float, bool, str.

2. A dagster config type: Int, Float, Bool, String, StringSource, Path, Any,
   Array, Noneable, Selector, Shape, Permissive, etc.

3. A bare python dictionary, which is wrapped in Shape. Any
   values in the dictionary get resolved by the same rules, recursively.

4. A bare python list of length one which itself is config type.
   Becomes Array with list element as an argument.
"""


@overload
def resolve_to_config_type(obj: Union[ConfigType, UserConfigSchema]) -> ConfigType:
    pass


@overload
def resolve_to_config_type(obj: object) -> Union[ConfigType, bool]:
    pass


def resolve_to_config_type(obj: object) -> Union[ConfigType, bool]:
    raise NotImplementedError()


def has_implicit_default(config_type):
    if config_type.kind == ConfigTypeKind.NONEABLE:
        return True

    return all_optional_type(config_type)


class Field:
    """Defines the schema for a configuration field.

    Fields are used in config schema instead of bare types when one wants to add a description,
    a default value, or to mark it as not required.

    Config fields are parsed according to their schemas in order to yield values available at
    job execution time through the config system. Config fields can be set on ops, on
    loaders for custom, and on other pluggable components of the system, such as resources, loggers,
    and executors.


    Args:
        config (Any): The schema for the config. This value can be any of:

            1. A Python primitive type that resolves to a Dagster config type
               (:py:class:`~python:int`, :py:class:`~python:float`, :py:class:`~python:bool`,
               :py:class:`~python:str`, or :py:class:`~python:list`).

            2. A Dagster config type:

               * :py:data:`~dagster.Any`
               * :py:class:`~dagster.Array`
               * :py:data:`~dagster.Bool`
               * :py:data:`~dagster.Enum`
               * :py:data:`~dagster.Float`
               * :py:data:`~dagster.Int`
               * :py:data:`~dagster.IntSource`
               * :py:data:`~dagster.Noneable`
               * :py:class:`~dagster.Permissive`
               * :py:class:`~dagster.ScalarUnion`
               * :py:class:`~dagster.Selector`
               * :py:class:`~dagster.Shape`
               * :py:data:`~dagster.String`
               * :py:data:`~dagster.StringSource`

            3. A bare python dictionary, which will be automatically wrapped in
               :py:class:`~dagster.Shape`. Values of the dictionary are resolved recursively
               according to the same rules.

            4. A bare python list of length one which itself is config type.
               Becomes :py:class:`Array` with list element as an argument.

        default_value (Any):
            A default value for this field, conformant to the schema set by the ``dagster_type``
            argument. If a default value is provided, ``is_required`` should be ``False``.

            Note: for config types that do post processing such as Enum, this value must be
            the pre processed version, ie use ``ExampleEnum.VALUE.name`` instead of
            ``ExampleEnum.VALUE``

        is_required (bool):
            Whether the presence of this field is required. Defaults to true. If ``is_required``
            is ``True``, no default value should be provided.

        description (str):
            A human-readable description of this config field.

    Examples:
        .. code-block:: python

            @op(
                config_schema={
                    'word': Field(str, description='I am a word.'),
                    'repeats': Field(Int, default_value=1, is_required=False),
                }
            )
            def repeat_word(context):
                return context.op_config['word'] * context.op_config['repeats']
    """

    def _resolve_config_arg(self, config):
        if isinstance(config, ConfigType):
            return config

        config_type = resolve_to_config_type(config)
        if not config_type:
            raise DagsterInvalidDefinitionError(
                (
                    "Attempted to pass {value_repr} to a Field that expects a valid "
                    "dagster type usable in config (e.g. Dict, Int, String et al)."
                ).format(value_repr=repr(config))
            )
        return config_type

    def __init__(
        self,
        config: Any,
        default_value: Any = FIELD_NO_DEFAULT_PROVIDED,
        is_required: Optional[bool] = None,
        description: Optional[str] = None,
    ):
        from .post_process import resolve_defaults
        from .validate import validate_config

        self.config_type = check.inst(self._resolve_config_arg(config), ConfigType)

        self._description = check.opt_str_param(description, "description")

        check.opt_bool_param(is_required, "is_required")

        if default_value != FIELD_NO_DEFAULT_PROVIDED:
            check.param_invariant(
                not (callable(default_value)),
                "default_value",
                "default_value cannot be a callable",
            )

        if is_required is True:
            check.param_invariant(
                default_value == FIELD_NO_DEFAULT_PROVIDED,
                "default_value",
                "required arguments should not specify default values",
            )

        self._default_value = default_value

        # check explicit default value
        if self.default_provided:
            if self.config_type.kind == ConfigTypeKind.ENUM and is_enum_value(
                default_value
            ):
                raise DagsterInvalidDefinitionError(
                    (
                        "You have passed into a python enum value as the default value "
                        "into of a config enum type {name}. You must pass in the underlying "
                        "string represention as the default value. One of {value_set}."
                    ).format(
                        value_set=[
                            ev.config_value for ev in self.config_type.enum_values
                        ],
                        name=self.config_type.given_name,
                    )
                )

            evr = validate_config(self.config_type, default_value)
            if not evr.success:
                raise DagsterInvalidConfigError(
                    "Invalid default_value for Field.",
                    evr.errors,
                    default_value,
                )

        if is_required is None:
            is_optional = (
                has_implicit_default(self.config_type) or self.default_provided
            )
            is_required = not is_optional

            # on implicitly optional - set the default value
            # by resolving the defaults of the type
            if is_optional and not self.default_provided:
                evr = resolve_defaults(self.config_type, None)
                if not evr.success:
                    raise DagsterInvalidConfigError(
                        "Unable to resolve implicit default_value for Field.",
                        evr.errors,
                        None,
                    )
                self._default_value = evr.value
        self._is_required = is_required

    @public
    @property
    def is_required(self) -> bool:
        return self._is_required

    @public
    @property
    def default_provided(self) -> bool:
        """Was a default value provided.

        Returns:
            bool: Yes or no
        """
        return self._default_value != FIELD_NO_DEFAULT_PROVIDED

    @public
    @property
    def default_value(self) -> Any:
        check.invariant(
            self.default_provided, "Asking for default value when none was provided"
        )
        return self._default_value

    @public
    @property
    def description(self) -> Optional[str]:
        return self._description

    @property
    def default_value_as_json_str(self) -> str:
        check.invariant(
            self.default_provided, "Asking for default value when none was provided"
        )
        return serialize_value(self.default_value)

    def __repr__(self) -> str:
        return (
            "Field({config_type}, default={default}, is_required={is_required})"
        ).format(
            config_type=self.config_type,
            default="@"
            if self._default_value == FIELD_NO_DEFAULT_PROVIDED
            else self._default_value,
            is_required=self.is_required,
        )


def check_opt_field_param(obj: object, param_name: str) -> Optional[Field]:
    return check.opt_inst_param(cast(Optional[Field], obj), param_name, Field)
