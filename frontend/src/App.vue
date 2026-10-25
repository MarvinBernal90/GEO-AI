<!--
==============================================================================
ROOT COMPONENT
==============================================================================
File: frontend/src/App.vue

Only hosts the router with KeepAlive caching for HomeView. Each page lives in src/views:
  HomeView     the viability dossier (route "/") - persisted on navigation
  MetricsView  the request metrics dashboard (route "/metrics")
-->
<template>
  <RouterView v-slot="{ Component }">
    <KeepAlive include="HomeView">
      <component :is="Component" />
    </KeepAlive>
  </RouterView>
</template>
