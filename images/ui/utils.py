from html import escape
import yaml, kubernetes, re, json
from kubernetes.client.rest import ApiException
from ansi2html import Ansi2HTMLConverter
from dateutil.tz import tzutc
import datetime

try:
    kubernetes.config.load_kube_config()
except:
    kubernetes.config.load_incluster_config()

API_GROUP = 'autotbx.io'
API_VERSION = 'v1'
_k8s_custom = kubernetes.client.CustomObjectsApi()
_k8s_core = kubernetes.client.CoreV1Api()
plurals = [
  "plans",
  "planrequests",
  "ansibleplans",
  "ansibleplanrequests",
  "states",
  "providers",
  "clusterproviders",
  "moduletemplates",
  "clustermoduletemplates",
  "modules"
]
namespace="default"

def getNamespace():
    ns = []
    for namespace in _k8s_core.list_namespace(label_selector="toolbox-managed=true").items:
        ns.append(namespace.metadata.name)
    return ns

def formatKind(kind, obj):
  name = obj["metadata"]["name"]
  namespace = obj["metadata"]["namespace"] if "namespace" in obj["metadata"] else None
  edit = '/edit' if kind not in ['plans', 'planrequests', 'ansibleplans', 'ansibleplanrequests'] else ""
  link = f'<a href="/{kind}/{namespace}/{name}{edit}">{name}</a>' if namespace != None else f'<a href="/cluster/{kind}/{name}{edit}">{name}</a>'
  if namespace:
    nslink = f'<a href="/{kind}/{namespace}/">{namespace}</a>'

  if kind == "states":
    return {
      'name' : link,
      'autoPlanApprove': obj["spec"]["autoPlanApprove"],
      'autoPlanRequest' : obj["spec"]['autoPlanRequest'],
      'deleteJobsOnPlanDeleted': obj["spec"]['deleteJobsOnPlanDeleted'],
      'clusterProviders' : escapeAttribute(','.join(obj["spec"]["clusterProviders"]) if "clusterProviders" in obj["spec"] else ""),
      'environment' : escapeAttribute(obj["spec"]["environment"] if "environment" in obj["spec"] else ""),
      'creationTimestamp' : obj["metadata"]["creationTimestamp"],
      'namespace' :  nslink
    }
  elif kind == "plans" or kind == "ansibleplans":
    return {
      'name' : link,
      'type' : 'terraform' if kind == "plans" else "ansible",
      'approved': obj["spec"]["approved"],
      'applyStatus' : obj["status"]['applyStatus'],
      'applyStartTime': escapeAttribute(obj["status"]['applyStartTime']),
      'applyCompleteTime': obj["status"]['applyCompleteTime'],
      'planStatus' : obj["status"]['planStatus'],
      'planStartTime': obj["status"]['planStartTime'],
      'planCompleteTime': escapeAttribute(obj["status"]['planCompleteTime']),
      'targets': escapeAttribute(','.join(obj["spec"]["targets"]) if "targets" in obj['spec'] else ''),
      'creationTimestamp' : obj["metadata"]["creationTimestamp"],
      'namespace' :  nslink
    }
  elif kind == "planrequests" or kind == "ansibleplanrequests":
    out = {
      'name' : link,
      'type' : 'terraform' if kind == "planrequests" else "ansible",
      'deletePlanOnDeleted': obj["spec"]["deletePlanOnDeleted"],
      'targets': escapeAttribute(','.join(obj["spec"]["targets"]) if "targets" in obj['spec'] else ''),
      'creationTimestamp' : obj["metadata"]["creationTimestamp"],
      'namespace' :  nslink
    }
    if "status" in obj and "plans" in obj["status"]:
      kt = 'plans' if kind == 'planrequests' else 'ansibleplans'
      out['plans'] = ','.join([ f'<a href="/{kt}/{namespace}/{escapeAttribute(x)}">{escapeAttribute(x)}</a>' for x in obj["status"]["plans"]])
    else:
      out['plans'] = ''
    return out
    
  elif kind == "providers" or kind == "clusterproviders":
    return {
      'name' : link,
      'type' : escapeAttribute(obj["spec"]["type"] if "type" in obj["spec"] else ""),
      'creationTimestamp' : obj["metadata"]["creationTimestamp"],
      'namespace':  nslink if "namespace" in obj["metadata"] else None
    }
  elif kind == "moduletemplates" or kind == "clustermoduletemplates":
    return {
      'name' : link,
      "requiredAttributes" : escapeAttribute(','.join([x['name'] for x in obj["spec"]["requiredAttributes"]]) if "requiredAttributes" in obj["spec"] else ""),
      'creationTimestamp' : obj["metadata"]["creationTimestamp"],
      'namespace' :  nslink if "namespace" in obj["metadata"] else None
    }
  elif kind == "modules":
    return {
      'name' : link,
      "autoPlanRequest": obj["spec"]["autoPlanRequest"],
      "clusterModuleTemplate": f'<a href="/cluster/clustermoduletemplates/{escapeAttribute(obj["spec"]["clusterModuleTemplate"])}/edit">{escapeAttribute(obj["spec"]["clusterModuleTemplate"])}</a>' if "clusterModuleTemplate" in obj["spec"] else "",
      "moduleTemplate": f'<a href="/moduletemplates/{namespace}/{escapeAttribute(obj["spec"]["moduleTemplate"])}/edit">{escapeAttribute(obj["spec"]["moduleTemplate"])}</a>' if "moduleTemplate" in obj["spec"] else "",
      'creationTimestamp' : obj["metadata"]["creationTimestamp"],
      'namespace' :  nslink
    }

def formData(request, method):
  body = {'spec' : {}}
  jsonfields = ["environments", "attributes", "defaultAttributes", "requiredAttributes", "ansibleAttributes"]
  for k in request.form:
      v = request.form[k]
      if k != "name" and k != "csrf_token":
        if k in jsonfields:
          try:
            v = json.loads(v)
          except  ApiException as e:
            print(f'unable to parse json : {v} {e}')
            return  None
        else:
          if k.endswith('[]'):
            v = request.form.getlist(k)
          else:
            if type(v) == type(""):
              if v.lower() == "true":
                v = True
              elif v.lower() == "false":
                v = False
        if method == "edit":
          if v != None:
            body['spec'][k.replace('[]','')] = v if v != "" or type(v) == type([]) else None
        else:
          if v != None and v != "":
            body['spec'][k.replace('[]','')] = v

  return body

def formatApiKind(name):
  m = {
    "plans": "Plan",
    "planrequests" : "PlanRequest",
    "ansibleplans": "AnsiblePlan",
    "ansibleplanrequests": "AnsiblePlanRequest",
    "states" : "State",
    "providers" : "Provider",
    "clusterproviders" : "ClusterProvider",
    "moduletemplates" : "ModuleTemplate",
    "clustermoduletemplates" : "ClusterModuleTemplate",
    "modules": "Module"
  }
  return m[name]


def getObj(plural, name, namespace=None):
    if not plural in plurals:
        return None
    if namespace == None:
        try:
            obj = _k8s_custom.get_cluster_custom_object(API_GROUP, API_VERSION, plural, name)
        except ApiException as e:
            print("Exception when calling CustomObjectsApi->get_cluster_custom_object: %s\n" % e)
            return None
    else:
        try:
            obj = _k8s_custom.get_namespaced_custom_object(API_GROUP, API_VERSION, namespace, plural , name)
        except ApiException as e:
            print("Exception when calling CustomObjectsApi->get_namespaced_custom_object: %s\n" % e)
            return None
    return obj


def getAttributeType(value):
  attrtype = ["sValue", "iValue", "nValue", "bValue", "lsValue", "liValue", "lnValue", "lbValue"]
  for t in attrtype:
    if t in value:
      return t

def escapeAttribute(values):
  if type(values) == type(''):
    return escape(values)
  if type(values) == type([]) and len(values) != 0 and type(values[0]) == type(''):
    return [escape(x) for x in values]
  if type(values) == type([]) and len(values) != 0 and type(values[0]) == type({}):
    if list(values[0].keys())[0] == 'fqdn':
      return [ {"fqdn" : escape(x['fqdn']), "vars" : escapeAttribute(x['vars']) if "vars" in x else []} for x in values ]
    else:
      return [ {"name": escape(x['name']), getAttributeType(x) : escapeAttribute(x[getAttributeType(x)])} for x in values]
  return values
  
def safeDump(form):
  i = 0
  for section in form:
    if section["id"] == "environments":
      j = 0
      for env in form[i]["fields"][0]["value"]:
        form[i]["fields"][0]["value"][j]["name"] = escapeAttribute(env["name"])
        for x in ["attributes", "defaultAttributes", "requiredAttributes"]:
          if x in form[i]["fields"][0]["value"][j]:
            form[i]["fields"][0]["value"][j][x] = escapeAttribute(env[x])
        if 'ansibleAttributes' in env:
          for x in ["roles", "dependencies", "vars"]:
            if x in form[i]["fields"][0]["value"][j]["ansibleAttributes"]:
              form[i]["fields"][0]["value"][j]["ansibleAttributes"][x] = escapeAttribute(env["ansibleAttributes"][x])
          if "credentials" in env["ansibleAttributes"]:
            for x in env["ansibleAttributes"]["credentials"]:
              form[i]["fields"][0]["value"][j]["ansibleAttributes"]["credentials"][x] = escapeAttribute(env["ansibleAttributes"]["credentials"][x])
            if "defaultGalaxyServer" in env["ansibleAttributes"]:
              form[i]["fields"][0]["value"][j]["ansibleAttributes"]["defaultGalaxyServer"] = escapeAttribute(env["ansibleAttributes"]["defaultGalaxyServer"])
        j = j + 1
    elif "fields" in section:
      j = 0
      for field in section["fields"]:
        if "value" in field:
          form[i]["fields"][j]["value"] = escapeAttribute(field['value'])
        j = j+1
    i = i+1
  return form

def getForm(plural, namespace=None):
    clproviders = _k8s_custom.list_cluster_custom_object(API_GROUP, API_VERSION, 'clusterproviders')["items"]
    cltemplates = _k8s_custom.list_cluster_custom_object(API_GROUP, API_VERSION, 'clustermoduletemplates')["items"]
    templates = _k8s_custom.list_namespaced_custom_object(API_GROUP, API_VERSION, namespace, 'moduletemplates')["items"] if namespace != None else []
    modules =  _k8s_custom.list_namespaced_custom_object(API_GROUP, API_VERSION, namespace, 'modules')["items"] if namespace != None else []
    clusterProviders = [k['metadata']["name"] for k in clproviders]
    clusterModuleTemplates  = [k['metadata']["name"] for k in cltemplates]
    moduleTemplates = [k['metadata']["name"] for k in templates]
    modules = [k['metadata']["name"] for k in modules]
    form = {
    "planrequests": [
      {
        "id" : "spec",
        "name": "Specification",
        "fields": [
        {
        "id": "name",
        "type": "string",
        "name": "Name",
        "required": True,
        },
        {
        "id": "deletePlanOnDeleted",
        "type": "boolean",
        "name": "Delete Plan On Deleted",
        "required": True,
        "value": True
        },
        {
        "id": "targets",
        "type": "list",
        "name": "Targets",
        "multiple": True,
        "values": [],
        "options": modules
        }
        ]
      }
    ],
    "providers": [
      {
      "id" : "spec",
      "name" : "Specification",
      "fields": [
        {
        "id": "name",
        "type": "string",
        "name": "Name",
        "required": True,
        "value": ""
        },
        {
        "id": "type",
        "type": "string",
        "name": "Type",
        "required": True
        }],
      },
      {
        "id": "attributes",
        "name": "Attributes",
        "add" : "insertAttribute",
        "fields": [
          {
            "type": "attributes",
            "id": "attributes",
            "value" : [],
          }
        ]
      }
    ],
    "clusterproviders": [
        {
      "id" : "spec",
      "name" : "Specification",
      "fields": [
        {
        "id": "name",
        "type": "string",
        "name": "Name",
        "required": True,
        "value": ""
        },
        {
        "id": "type",
        "type": "string",
        "name": "Type",
        "required": True
        }],
      },
      {
        "id": "attributes",
        "name": "Attributes",
        "add" : "insertAttribute",
        "fields": [
          {
            "type": "attributes",
            "id": "attributes",
            "value" : [],
          }
        ]
      },
      {
        "id" : "environments",
        "name" : "Environments",
        "add": "addEnv",
        "fields": [
          {
            "type": "environments",
            "id": "environments",
            "value" : [],
          }
        ]
      }
    ],
    "modules": [
      {
        "id": "spec",
        "name": 'Specification <button type="button" class="btn btn-dark showtplattr">Show herited configuration</button>',
        "fields": [
          {
          "id": "name",
          "type": "string",
          "name": "Name",
          "required": True,
          "value": ""
          },
          {
          "id": "autoPlanRequest",
          "type": "boolean",
          "name": "Auto Plan Request",
          "required": True,
          "value": True
          },
          {
          "id": "clusterModuleTemplate",
          "type": "list",
          "name": "Cluster Module Template",
          "options" : clusterModuleTemplates,
          },
          {
          "id": "moduleTemplate",
          "type": "list",
          "name": "Module Template",
          "options" : moduleTemplates
          },
        ]
      },
      {
        "id": "requiredAttributes",
        "name": "Required Attributes",
        "fields": [
          {
            "type": "fillRequiredAttributes",
            "id": "requiredAttributes",
            "value" : [],
          }
        ]
      },
      {
        "id": "attributes",
        "name": "Attributes",
        "add" : "insertAttribute",
        "fields": [
          {
            "type": "attributes",
            "id": "attributes",
            "value" : [],
          }
        ]
      },
      {
        "id": "ansibleHosts",
        "name": "Ansible Hosts",
        "fields": [
          {
            "type": "ansibleHosts",
            "id": "ansibleHosts",
            "value" : [],
          }
        ]
      },
      {
        "id": "ansibleSpec",
        "name": "Ansible Specification",
        "fields": [
        {
          "id": "ansible_cred_type",
          "name": "Authentication Type",
          "type": "list",
          "options": ["ssh", "winrm"],
        },
        {
          "id": "ansible_cred_user",
          "name": "Username",
          "type": "string",
        },
        {
          "id": "ansible_cred_password",
          "name": "Password",
          "type": "string",
        },
        {
          "id": "ansible_cred_ssh_key",
          "name": "SSH Key",
          "type": "string",
        },
        {
          "id": "ansible_defaultGalaxyServer",
          "type": "string",
          "name": "Default Galaxy Server",
        },
        ]
      },
      {
        "id": "ansibleRoles",
        "name": "Ansible Roles",
        "fields": [
          {
            "type": "ansibleRoles",
            "id": "ansibleRoles",
            "value" : [],
          }
        ]
      },
      {
        "id": "ansibleVars",
        "name": "Ansible Variables",
        "add" : "insertAttribute",
        "fields": [
          {
            "type": "attributes",
            "id": "ansibleVars",
            "value" : [],
          }
        ]
      },
      {
        "id": "ansibleDependencies",
        "name": "Ansible Dependencies",
        "fields": [
          {
            "type": "ansibleDependencies",
            "id": "ansibleDependencies",
            "value" : [],
          }
        ]
      },
    ],
    "clustermoduletemplates": [
      {
      "id" : "spec",
      "name" : "Specification",
      "fields": [
        {
        "id": "name",
        "type": "string",
        "name": "Name",
        "required": True,
        "value": ""
        },
        ],
      },
      {
        "id": "requiredAttributes",
        "name": "Required Attributes",
        "add" : "insertRequiredAttribute",
        "fields": [
          {
            "type": "requiredAttributes",
            "id": "requiredAttributes",
            "value" : [],
          }
        ]
      },
      {
        "id": "defaultAttributes",
        "name": "Default Attributes",
        "add" : "insertAttribute",
        "fields": [
          {
            "type": "attributes",
            "id": "defaultAttributes",
            "value" : [],
          }
        ]
      },
      {
        "id": "ansibleSpec",
        "name": "Ansible Specification",
        "fields": [
        {
          "id": "ansible_cred_type",
          "name": "Authentication Type",
          "type": "list",
          "options": ["ssh", "winrm"],
        },
        {
          "id": "ansible_cred_user",
          "name": "Username",
          "type": "string",
        },
        {
          "id": "ansible_cred_password",
          "name": "Password",
          "type": "string",
        },
        {
          "id": "ansible_cred_ssh_key",
          "name": "SSH Key",
          "type": "string",
        },
        {
          "id": "ansible_defaultGalaxyServer",
          "type": "string",
          "name": "Default Galaxy Server",
        },
        ]
      },
      {
        "id": "ansibleRoles",
        "name": "Ansible Roles",
        "fields": [
          {
            "type": "ansibleRoles",
            "id": "ansibleRoles",
            "value" : [],
          }
        ]
      },
      {
        "id": "ansibleVars",
        "name": "Ansible Variables",
        "add" : "insertAttribute",
        "fields": [
          {
            "type": "attributes",
            "id": "ansibleVars",
            "value" : [],
          }
        ]
      },
      {
        "id": "ansibleDependencies",
        "name": "Ansible Dependencies",
        "fields": [
          {
            "type": "ansibleDependencies",
            "id": "ansibleDependencies",
            "value" : [],
          }
        ]
      },
      {
        "id" : "environments",
        "name" : "Environments",
        "add": "addEnv",
        "fields": [
          {
            "type": "environments",
            "id": "environments",
            "value" : [],
          }
        ]
      }
    ],
    "moduletemplates": [
      {
      "id" : "spec",
      "name" : "Specification",
      "fields": [
        {
        "id": "name",
        "type": "string",
        "name": "Name",
        "required": True,
        "value": ""
        },
        ],
      },
      {
        "id": "requiredAttributes",
        "name": "Required Attributes",
        "add" : "insertRequiredAttribute",
        "fields": [
          {
            "type": "requiredAttributes",
            "id": "requiredAttributes",
            "value" : [],
          }
        ]
      },
      {
        "id": "defaultAttributes",
        "name": "Default Attributes",
        "add" : "insertAttribute",
        "fields": [
          {
            "type": "attributes",
            "id": "defaultAttributes",
            "value" : [],
          }
        ]
      },
      {
        "id": "ansibleSpec",
        "name": "Ansible Specification",
        "fields": [
        {
          "id": "ansible_cred_type",
          "name": "Authentication Type",
          "type": "list",
          "options": ["ssh", "winrm"],
        },
        {
          "id": "ansible_cred_user",
          "name": "Username",
          "type": "string",
        },
        {
          "id": "ansible_cred_password",
          "name": "Password",
          "type": "string",
        },
        {
          "id": "ansible_cred_ssh_key",
          "name": "SSH Key",
          "type": "string",
        },
        {
          "id": "ansible_defaultGalaxyServer",
          "type": "string",
          "name": "Default Galaxy Server",
        },
        ]
      },
      {
        "id": "ansibleRoles",
        "name": "Ansible Roles",
        "fields": [
          {
            "type": "ansibleRoles",
            "id": "ansibleRoles",
            "value" : [],
          }
        ]
      },
      {
        "id": "ansibleVars",
        "name": "Ansible Variables",
        "add" : "insertAttribute",
        "fields": [
          {
            "type": "attributes",
            "id": "ansibleVars",
            "value" : [],
          }
        ]
      },
      {
        "id": "ansibleDependencies",
        "name": "Ansible Dependencies",
        "fields": [
          {
            "type": "ansibleDependencies",
            "id": "ansibleDependencies",
            "value" : [],
          }
        ]
      },
    ],
    "states" : [
    {
      "id": "spec",
      "name": "Specification",
      "fields": [
        {
        "id": "name",
        "type": "string",
        "name": "Name",
        "required": True,
        },
        {
        "id": "autoPlanApprove",
        "type": "boolean",
        "name": "Auto Plan Approve",
        "required": True,
        "value": False
        },
        {
        "id": "autoPlanRequest",
        "type": "boolean",
        "name": "Auto Plan Request",
        "required": True,
        "value": True
        },
        {
        "id": "deleteJobsOnPlanDeleted",
        "type": "boolean",
        "name": "Auto Delete Job On Plan Deleted",
        "required": True,
        "value": True
        },
        {
        "id": "environment",
        "type": "string",
        "name": "Environment",
        },
        {
        "id": "clusterProviders",
        "type": "list",
        "name": "Cluster Providers",
        "multiple": True,
        "options" : clusterProviders
        },
        {
        "id": "customTerraformInit",
        "type": "textarea",
        "name": "Custom Terraform Init",
        },
        {
        "id": "terraformOption",
        "type": "string",
        "name": "Terraform option",
        },
        {
        "id": "tfExecutorImage",
        "type": "string",
        "name": "TF Executor Image",
        },
        {
        "id": "tfExecutorImagePullPolicy",
        "type": "list",
        "name": "TF Executor Image Pull Policy",
        "options": ["Always", "Never", "IfNotPresent"],
        },
        {
        "id": "tfGeneratorImage",
        "type": "string",
        "name": "TF Generator Image",
        },
        {
        "id": "tfGeneratorImagePullPolicy",
        "type": "list",
        "name": "TF Generator Image Pull Policy",
        "options": ["Always", "Never", "IfNotPresent"],
        },
        {
        "id": "ansibleExecutorImage",
        "type": "string",
        "name": "Ansible Executor Image",
        },
        {
        "id": "ansibleExecutorImagePullPolicy",
        "type": "list",
        "name": "Ansible Executor Image Pull Policy",
        "options": ["Always", "Never", "IfNotPresent"],
        },
        {
        "id": "ansibleGeneratorImage",
        "type": "string",
        "name": "Ansible Generator Image",
        },
        {
        "id": "ansibleGeneratorImagePullPolicy",
        "type": "list",
        "name": "Ansible Generator Image Pull Policy",
        "options": ["Always", "Never", "IfNotPresent"],
        },
        {
          "id" : "trustedCA",
          "type": "textarea",
          "name": "Trusted CA",
          "value": "",
        }
      ]
    }
    ]
    }
    form['ansibleplanrequests'] = form['planrequests']
    #form['ans'] = form['planrequests']
    #form['clusterproviders'] = form['providers']
    #form['clustermoduletemplates'] = form['moduletemplates']
    return form[plural]

def updateFieldsValues(form, plural, obj):
  if plural == "planrequests" or plural == "ansibleplanrequests":
    form = updateFieldsValue(form, "spec", "name", "value", obj['metadata']['name'])
    form = updateFieldsValue(form, "spec", "name", "disabled", True)
    form = updateFieldsValue(form, "spec", "deletePlanOnDeleted", "value", obj['spec']['deletePlanOnDeleted'])
  elif plural == "states":
    form = updateFieldsValue(form, "spec", "name", "value", obj['metadata']['name'])
    form = updateFieldsValue(form, "spec", "name", "disabled", True)
    form = updateFieldsValue(form, "spec", "autoPlanApprove", "value", obj['spec']['autoPlanApprove'])
    form = updateFieldsValue(form, "spec", "autoPlanRequest", "value", obj['spec']['autoPlanRequest'])
    form = updateFieldsValue(form, "spec", "deleteJobsOnPlanDeleted", "value", obj['spec']['deleteJobsOnPlanDeleted'])
    form = updateFieldsValue(form, "spec", "customTerraformInit", "value", obj['spec']['customTerraformInit'] if "customTerraformInit" in obj['spec'] else '')
    form = updateFieldsValue(form, "spec", "tfExecutorImage", "value", obj['spec']['tfExecutorImage'])
    form = updateFieldsValue(form, "spec", "tfExecutorImagePullPolicy", "value", obj['spec']['tfExecutorImagePullPolicy'])
    form = updateFieldsValue(form, "spec", "tfGeneratorImage", "value", obj['spec']['tfGeneratorImage'])
    form = updateFieldsValue(form, "spec", "tfGeneratorImagePullPolicy", "value", obj['spec']['tfGeneratorImagePullPolicy'])
    form = updateFieldsValue(form, "spec", "ansibleExecutorImage", "value", obj['spec']['ansibleExecutorImage'])
    form = updateFieldsValue(form, "spec", "ansibleExecutorImagePullPolicy", "value", obj['spec']['ansibleExecutorImagePullPolicy'])
    form = updateFieldsValue(form, "spec", "ansibleGeneratorImage", "value", obj['spec']['ansibleGeneratorImage'])
    form = updateFieldsValue(form, "spec", "ansibleGeneratorImagePullPolicy", "value", obj['spec']['ansibleGeneratorImagePullPolicy'])
    form = updateFieldsValue(form, "spec", "clusterProviders", "values", obj['spec']['clusterProviders'] if "clusterProviders" in obj["spec"] else [])
    form = updateFieldsValue(form, "spec", "environment", "value", obj['spec']['environment'] if 'environment' in obj["spec"] else [])
    form = updateFieldsValue(form, "spec", "trustedCA", "value", obj['spec']['trustedCA'] if "trustedCA" in obj["spec"] else "")
    form = updateFieldsValue(form, "spec", "terraformOption", "value", obj['spec']['terraformOption'] if "terraformOption" in obj["spec"] else "")
  elif plural == "providers" or plural == "clusterproviders":
    form = updateFieldsValue(form, "spec", "name", "value", obj['metadata']['name'])
    form = updateFieldsValue(form, "spec", "name", "disabled", True)
    form = updateFieldsValue(form, "spec", "type", "value", obj['spec']['type'])
    form = updateFieldsValue(form, "environments", "environments", "value", obj['spec']['environments'] if 'environments' in obj["spec"] else [])
    form = updateFieldsValue(form, "attributes", "attributes", "value", obj['spec']['attributes'] if 'attributes' in obj["spec"] else [])
  elif plural == "moduletemplates" or plural == "clustermoduletemplates":
    form = updateFieldsValue(form, "spec", "name", "value", obj['metadata']['name'])
    form = updateFieldsValue(form, "spec", "name", "disabled", True)
    form = updateFieldsValue(form, "environments", "environments", "value", obj['spec']['environments'] if 'environments' in obj["spec"] else [])
    form = updateFieldsValue(form, "defaultAttributes", "defaultAttributes", "value", obj['spec']['defaultAttributes'] if 'defaultAttributes' in obj["spec"] else [])
    if "ansibleAttributes" in obj['spec']:
      if  "credentials" in obj['spec']['ansibleAttributes']:
        form = updateFieldsValue(form, "ansibleSpec", "ansible_cred_type", "value", obj['spec']['ansibleAttributes']['credentials']['type'] if "type" in obj['spec']['ansibleAttributes']["credentials"] else '')
        form = updateFieldsValue(form, "ansibleSpec", "ansible_cred_user", "value", obj['spec']['ansibleAttributes']['credentials']['user'] if "user" in obj['spec']['ansibleAttributes']["credentials"] else '')
        form = updateFieldsValue(form, "ansibleSpec", "ansible_cred_password", "value", obj['spec']['ansibleAttributes']['credentials']['password'] if "password" in obj['spec']['ansibleAttributes']["credentials"] else '')
        form = updateFieldsValue(form, "ansibleSpec", "ansible_cred_ssh_key", "value", obj['spec']['ansibleAttributes']['credentials']['ssh_key'] if "ssh_key" in obj['spec']['ansibleAttributes']["credentials"] else '')
      form = updateFieldsValue(form, "ansibleSpec", "ansible_defaultGalaxyServer", "value", obj['spec']['ansibleAttributes']['defaultGalaxyServer'] if "defaultGalaxyServer" in obj['spec']['ansibleAttributes'] else '')
      form = updateFieldsValue(form, "ansibleRoles", "ansibleRoles", "value", obj['spec']['ansibleAttributes']['roles'] if "roles" in obj['spec']['ansibleAttributes'] else [])
      form = updateFieldsValue(form, "ansibleDependencies", "ansibleDependencies", "value", obj['spec']['ansibleAttributes']['dependencies'] if "dependencies" in obj['spec']['ansibleAttributes'] else [])
      form = updateFieldsValue(form, "ansibleVars", "ansibleVars", "value", obj['spec']['ansibleAttributes']['vars'] if "vars" in obj['spec']['ansibleAttributes'] else [])
    attrs = []
    if 'requiredAttributes' in obj['spec']:
      for attr in obj['spec']['requiredAttributes']:
       #get = getAttribute(attr['name'], obj['spec']['attributes'], attr['type'])
        attrs.append({'name' : attr['name'], attr['type'] : '' })
    form = updateFieldsValue(form, "requiredAttributes", "requiredAttributes", "value", attrs)
  elif plural == "modules":
    form = updateFieldsValue(form, "spec", "name", "value", obj['metadata']['name'])
    form = updateFieldsValue(form, "spec", "name", "disabled", True)
    form = updateFieldsValue(form, "spec", "moduleTemplate", "value", obj['spec']['moduleTemplate']  if 'moduleTemplate' in obj["spec"] else "")
    form = updateFieldsValue(form, "spec", "clusterModuleTemplate", "value", obj['spec']['clusterModuleTemplate']  if 'clusterModuleTemplate' in obj["spec"] else "")
    form = updateFieldsValue(form, "spec", "autoPlanRequest", "value", obj['spec']['autoPlanRequest'])
    attributes = obj['spec']['attributes']
    tplobj = None
    if 'clusterModuleTemplate' in obj["spec"]:
      try:
        tplobj = _k8s_custom.get_cluster_custom_object(API_GROUP, API_VERSION, 'clustermoduletemplates', obj["spec"]['clusterModuleTemplate'])
      except ApiException as e:
        print("Exception when calling CustomObjectsApi->get_cluster_custom_object: %s\n" % e)
        tplobj = None
    elif 'moduleTemplate' in obj["spec"]:
      try:
        tplobj = _k8s_custom.get_namespaced_custom_object(API_GROUP, API_VERSION, namespace, 'moduletemplates', obj["spec"]['moduleTemplate'])
      except ApiException as e:
        print("Exception when calling CustomObjectsApi->get_namespaced_custom_object: %s\n" % e)      
        tplobj = None    
    if tplobj != None:
      attrs = []
      for attr in tplobj['spec']['requiredAttributes']:
        try:
          get = getAttribute(attr['name'], obj['spec']['attributes'], attr['type'])
        except KeyError:
          #module <-> template type mismatch,
          get = ''
        if get != None:
          attributes = popAttribute(attr['name'], attributes)
        attrs.append({'name' : attr['name'], attr['type'] : get if get != '' and get != None else [] if attr['type'].startswith('l') else '' })
      form = updateFieldsValue(form, "requiredAttributes", "requiredAttributes", "value", attrs)
    form = updateFieldsValue(form, "attributes", "attributes", "value", attributes)
    if "ansibleAttributes" in obj["spec"]:
      if  "credentials" in obj['spec']['ansibleAttributes']:
        form = updateFieldsValue(form, "ansibleSpec", "ansible_cred_type", "value", obj['spec']['ansibleAttributes']['credentials']['type'] if "type" in obj['spec']['ansibleAttributes']["credentials"] else '')
        form = updateFieldsValue(form, "ansibleSpec", "ansible_cred_user", "value", obj['spec']['ansibleAttributes']['credentials']['user'] if "user" in obj['spec']['ansibleAttributes']["credentials"] else '')
        form = updateFieldsValue(form, "ansibleSpec", "ansible_cred_password", "value", obj['spec']['ansibleAttributes']['credentials']['password'] if "password" in obj['spec']['ansibleAttributes']["credentials"] else '')
        form = updateFieldsValue(form, "ansibleSpec", "ansible_cred_ssh_key", "value", obj['spec']['ansibleAttributes']['credentials']['ssh_key'] if "ssh_key" in obj['spec']['ansibleAttributes']["credentials"] else '')
      form = updateFieldsValue(form, "ansibleSpec", "ansible_defaultGalaxyServer", "value", obj['spec']['ansibleAttributes']['defaultGalaxyServer'] if "defaultGalaxyServer" in obj['spec']['ansibleAttributes'] else '')
      form = updateFieldsValue(form, "ansibleRoles", "ansibleRoles", "value", obj['spec']['ansibleAttributes']['roles'] if "roles" in obj['spec']['ansibleAttributes'] else [])
      form = updateFieldsValue(form, "ansibleDependencies", "ansibleDependencies", "value", obj['spec']['ansibleAttributes']['dependencies'] if "dependencies" in obj['spec']['ansibleAttributes'] else [])
      form = updateFieldsValue(form, "ansibleVars", "ansibleVars", "value", obj['spec']['ansibleAttributes']['vars'] if "vars" in obj['spec']['ansibleAttributes'] else [])
      form = updateFieldsValue(form, "ansibleHosts", "ansibleHosts", "value", obj['spec']['ansibleAttributes']['targets'] if "targets" in obj['spec']['ansibleAttributes'] else [])
  return form

def updateFieldsValue(form, section, keyid, attr, val):
  j = 0
  for sec in form:
    if sec["id"] == section:
      i = 0
      for k in sec["fields"]:
        #print(k)
        if k["id"] == keyid:
          form[j]['fields'][i][attr] = val
        i = i + 1
    j = j + 1
  return form

def popAttribute(attribute, attributes):
  out = []
  for attr in attributes:
    if attr['name'] != attribute:
      out.append(attr)
  return out

def getAttribute(attribute, attributes, attrtype):
  for attr in attributes:
    if attr['name'] == attribute:
      return attr[attrtype]
  return None

def apiMapping(kind):
  if kind == "states":
    return [
        { "name" : "Name", "field": "name"},
        { "name" : "autoPlanApprove", "field": "autoPlanApprove"},
        { "name" : "autoPlanRequest", "field": "autoPlanRequest"},
        { "name" : "deleteJobsOnPlanDeleted", "field": "deleteJobsOnPlanDeleted"},
        { "name" : "deletePlansOnPlanDeleted", "field": "deletePlansOnPlanDeleted"},
        { "name" : "clusterProviders", "field": "clusterProviders"},
        { "name" : "Environment", "field" : "environment"},
        { "name" : "CreationTime", "field": "creationTimestamp"},
    ]
  elif kind == "plans" or kind == "ansibleplans":
    return [
      { "name" : "Name", "field": "name"},
      { "name" : "Type", "field": "type"},
      { "name" : "Approved", "field": "approved"},
      { "name" : "Plan", "field": "planStatus"},
      { "name" : "Plan Start", "field": "planStartTime"},
      { "name" : "Plan End", "field": "planCompleteTime"},
      { "name" : "Apply", "field": "applyStatus"},
      { "name" : "Apply Start", "field": "applyStartTime"},
      { "name" : "Apply End", "field": "applyCompleteTime"},
      { "name" : "Targets", "field": "targets"},
      { "name" : "CreationTime", "field": "creationTimestamp"},
    ]
  elif kind == "planrequests" or kind == "ansibleplanrequests":
    return [
      { "name" : "Name", "field": "name"},
      { "name" : "Type", "field": "type"},
      { "name" : "Plans", "field": "plans"},
      { "name" : "deletePlanOnDeleted", "field": "deletePlanOnDeleted"},
      { "name" : "Targets", "field": "targets"},
      { "name" : "CreationTime", "field": "creationTimestamp"},
    ]
  elif kind == "providers" or kind == "clusterproviders":
    return [
      { "name": "Name", "field": "name"},
      { "name": "Type", "field": "type"},
      { "name" : "CreationTime", "field": "creationTimestamp"},
    ]
  elif kind == "moduletemplates" or kind == "clustermoduletemplates":
    return [
      {"name" : "Name", "field": "name"},
      {"name" : "requiredAttributes:", "field": "requiredAttributes"},
      { "name" : "CreationTime", "field": "creationTimestamp"},
    ]
  elif kind == "modules":
    return [
      {"name" : "Name", "field": "name"},
      {"name" : "autoPlanRequest", "field": "autoPlanRequest"},
      {"name" : "clusterModuleTemplate", "field": "clusterModuleTemplate"},
      {"name" : "moduleTemplate", "field": "moduleTemplate"},
      { "name" : "CreationTime", "field": "creationTimestamp"},
    ]

def ansi2html(output):
  output = Ansi2HTMLConverter().convert(output)
  b = re.search(f'.*<body [^>]*>(.*)</body>.*', output, flags=re.DOTALL)
  c = re.search(f'.*<style.*>(.*)</style>.*', output, flags=re.DOTALL)
  if b == None or c == None:
    print(f'ERROR: unable to parse output : {output}')
    return ("", "")
  return (b.group(1), c.group(1))

def genTable(mapping, name, ajax,):
  ths = ""
  sortindex = 0
  i = 0
  for k in mapping:
    if k["name"] == "CreationTime":
      sortindex = i
    ths+= f'<th>{k["name"]}</th>'
    i = i + 1
  table = f'<table id="{name}" class="table" style="width:100%"><thead><tr>{ths}</tr></thead></table>'

  js = """
    var data;
    function formatDate(d) {
      console.log(d);
      var date = new Date(d);
      return date.getFullYear() + "-" + (date.getMonth()+1).toString().padStart(2,'0') + "-" + date.getDate().toString().padStart(2,'0') + " " + date.getHours() + ":" + date.getMinutes() + ":" + date.getSeconds()
    }
    table = $("#%NAME%").DataTable( {
        "ajax": "%AJAX%",
        "createdRow": function( row, data, dataIndex){
            $(row).addClass('table-row');
            $("td", row).filter(function() {
               return this.innerHTML.match(/\d+\-\d+\-\d+T\d+:\d+:\d+Z/)
            }).each(function() { $(this).html(formatDate($(this).html())) });
            $("td:contains('Failed')", row).css("color", "red");
            $("td:contains('Pending')", row).css("color", "orange");
            $("td:contains('Completed')", row).css("color", "green");
            $("td:contains('Active')", row).css("color", "yellow");

      //    if( data[2] ==  "someVal"){
        },
        "fnInitComplete": function(oSettings, json) {
          $(".dataTables_length select").addClass("table-input");
          $(".dataTables_length").addClass("table-length");
          $(".dataTables_filter input").addClass("table-input");
          $(".dataTables_filter").addClass("table-length");
          $(".dataTables_info").addClass("table-length");
        },
        "order": [["""+str(sortindex)+""", 'desc']],
        "columns": [
  """
  i=0
  for k in mapping:
    js += '{"data": "'+mapping[i]["field"]+'"},'
    i = i + 1
  js += """
        ]
    });
    //$('<button class="table-button" id="refresh">Refresh</button>').appendTo("div.dataTables_filter");
    //$("#%NAME% tbody").on("click", "tr", function () {
    //    var data = table.row( this ).data();
    //    location.href = "/plan/"+data["name"];
    //} );
  """
  js = js.replace('%NAME%', name).replace('%AJAX%', ajax)
  return (table, js)
